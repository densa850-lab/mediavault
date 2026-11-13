package app.densa.mediavault.data.auth

import app.densa.mediavault.data.remote.NetworkModule
import java.io.IOException
import kotlinx.coroutines.CancellationException
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
            store.save(StoredTokens(body.accessToken, body.refreshToken))
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

    private suspend fun refreshAndRetry(tokens: StoredTokens): SessionState {
        val rotated = api.refresh(RefreshDto(tokens.refreshToken))
        val pair = rotated.body()
        if (!rotated.isSuccessful || pair == null) {
            // Expired, revoked or reused refresh token: the session is over.
            store.clear()
            return SessionState.SignedOut
        }
        store.save(StoredTokens(pair.accessToken, pair.refreshToken))
        val me = api.me(bearer(pair.accessToken))
        val user = me.body()
        return if (me.isSuccessful && user != null) {
            SessionState.SignedIn(user)
        } else {
            store.clear()
            SessionState.SignedOut
        }
    }

    /** Revokes the session on the server (best effort) and always forgets the tokens locally. */
    override suspend fun logout() {
        val tokens = store.read()
        try {
            if (tokens != null) api.logout(bearer(tokens.accessToken), LogoutDto(tokens.refreshToken))
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            // Server unreachable: local sign-out still happens.
        } finally {
            store.clear()
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

        fun bearer(token: String) = "Bearer $token"

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
