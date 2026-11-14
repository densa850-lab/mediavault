package app.densa.mediavault.data.auth

import app.densa.mediavault.data.remote.NetworkModule
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import retrofit2.Response

const val MIN_PASSWORD_LENGTH = 12

sealed interface AuthOutcome {
    data object Success : AuthOutcome
    data class Failure(val message: String) : AuthOutcome
}

sealed interface SessionState {
    data class SignedIn(val user: UserDto) : SessionState
    data object SignedOut : SessionState
    data class Unavailable(val message: String) : SessionState
}

interface AuthRepository {
    suspend fun register(email: String, password: String): AuthOutcome
    suspend fun login(email: String, password: String): AuthOutcome
    suspend fun currentSession(): SessionState
    suspend fun logout()
}

class NetworkAuthRepository(private val api: AuthApi, private val store: TokenStore) : AuthRepository {

    /**
     * Serialises every change to the stored tokens (refresh, login, logout). Overlapping
     * currentSession() calls therefore share ONE refresh: the first caller rotates the token and
     * the others, after waiting, see that the stored pair already changed and reuse it instead of
     * presenting the old (now used) refresh token again. Logout waits for an in-flight refresh, so
     * it revokes and clears the newest pair and a late refresh can never resurrect stale tokens.
     */
    private val tokenLock = Mutex()

    override suspend fun register(email: String, password: String): AuthOutcome {
        if (password.length < MIN_PASSWORD_LENGTH) {
            return AuthOutcome.Failure("Password must be at least $MIN_PASSWORD_LENGTH characters.")
        }
        return call {
            val res = api.register(CredentialsDto(email.trim(), password))
            if (res.code() == 202 || res.isSuccessful) AuthOutcome.Success else failure(res, "Registration failed.")
        }
    }

    override suspend fun login(email: String, password: String): AuthOutcome = call {
        val res = api.login(CredentialsDto(email.trim(), password))
        val body = res.body()
        if (res.isSuccessful && body != null) {
            tokenLock.withLock { store.save(StoredTokens(body.accessToken, body.refreshToken)) }
            AuthOutcome.Success
        } else {
            failure(res, INVALID_CREDENTIALS)
        }
    }

    /** Who is signed in. Rotates the refresh token once if the access token was rejected. */
    override suspend fun currentSession(): SessionState {
        val tokens = store.read() ?: return SessionState.SignedOut
        return try {
            val me = api.me(bearer(tokens.accessToken))
            val user = me.body()
            when {
                me.isSuccessful && user != null -> SessionState.SignedIn(user)
                me.code() == 401 -> refreshAndRetry(tokens)
                else -> SessionState.Unavailable("Server error (HTTP ${me.code()}).")
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            SessionState.Unavailable(UNREACHABLE)
        } catch (e: SerializationException) {
            SessionState.Unavailable("Unexpected response from the server.")
        }
    }

    private suspend fun refreshAndRetry(stale: StoredTokens): SessionState = tokenLock.withLock {
        val current = store.read() ?: return@withLock SessionState.SignedOut
        if (current != stale) {
            // Another caller already refreshed (or signed in again) while we waited: use its pair.
            val me = api.me(bearer(current.accessToken))
            val user = me.body()
            if (me.isSuccessful && user != null) return@withLock SessionState.SignedIn(user)
            if (me.code() != 401) return@withLock SessionState.Unavailable("Server error (HTTP ${me.code()}).")
        }
        // A network error here propagates to currentSession(), which reports Unavailable and keeps
        // the tokens.
        val rotated = api.refresh(RefreshDto(current.refreshToken))
        val pair = rotated.body()
        if (rotated.isSuccessful && pair != null) {
            store.save(StoredTokens(pair.accessToken, pair.refreshToken))
        } else if (refreshDefinitelyRejected(rotated.code())) {
            // Expired, revoked, reused or malformed refresh token: the session is over.
            store.clear()
            return@withLock SessionState.SignedOut
        } else {
            // 429, 5xx or anything unexpected: temporary. Keep the tokens (MV-023).
            return@withLock SessionState.Unavailable(temporaryMessage(rotated.code()))
        }
        val me = api.me(bearer(pair.accessToken))
        val user = me.body()
        when {
            me.isSuccessful && user != null -> SessionState.SignedIn(user)
            me.code() == 401 -> {
                store.clear()
                SessionState.SignedOut
            }
            // The new pair is already saved; just report the temporary problem.
            else -> SessionState.Unavailable(temporaryMessage(me.code()))
        }
    }

    /**
     * Revokes the session on the server and always forgets the tokens locally. A temporary failure
     * (429, 5xx, network) is retried once before giving up on the server-side revoke (MV-024).
     */
    override suspend fun logout() {
        tokenLock.withLock {
            val tokens = store.read()
            try {
                if (tokens != null) {
                    repeat(LOGOUT_ATTEMPTS) {
                        val ok = try {
                            api.logout(bearer(tokens.accessToken), LogoutDto(tokens.refreshToken)).isSuccessful
                        } catch (e: CancellationException) {
                            throw e
                        } catch (_: IOException) {
                            false
                        }
                        if (ok) return@withLock
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                // Unexpected response: local sign-out still happens.
            } finally {
                store.clear()
            }
        }
    }

    private suspend fun call(block: suspend () -> AuthOutcome): AuthOutcome =
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            AuthOutcome.Failure(UNREACHABLE)
        } catch (e: SerializationException) {
            AuthOutcome.Failure("Unexpected response from the server.")
        }

    private fun failure(res: Response<*>, fallback: String): AuthOutcome.Failure =
        when (res.code()) {
            401 -> AuthOutcome.Failure(INVALID_CREDENTIALS)
            429 -> AuthOutcome.Failure("Too many attempts. Try again later.")
            422 -> AuthOutcome.Failure(validationMessage(res.errorBody()?.string()) ?: fallback)
            else -> AuthOutcome.Failure(fallback)
        }

    companion object {
        const val INVALID_CREDENTIALS = "Invalid email or password."
        const val UNREACHABLE = "The MediaVault server could not be reached."

        const val LOGOUT_ATTEMPTS = 2

        fun bearer(token: String) = "Bearer $token"

        /** Only these answers mean the refresh token can never work again (MV-023). */
        fun refreshDefinitelyRejected(code: Int) = code == 401 || code == 422

        fun temporaryMessage(code: Int) = when (code) {
            429 -> "The server is busy. You are still signed in; try again in a moment."
            else -> "Server error (HTTP $code). You are still signed in; try again in a moment."
        }

        /** First FastAPI validation message, e.g. "Password must be at least 12 characters." */
        fun validationMessage(raw: String?): String? = runCatching {
            val detail = NetworkModule.json.parseToJsonElement(raw ?: return null).jsonObject["detail"]
            val msg = when (detail) {
                is JsonPrimitive -> detail.content
                is JsonArray -> (detail.firstOrNull() as? JsonObject)?.get("msg")?.jsonPrimitive?.content
                else -> null
            }
            msg?.removePrefix("Value error, ")
        }.getOrNull()
    }
}
