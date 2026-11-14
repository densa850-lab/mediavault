package app.densa.mediavault.data.auth

import kotlinx.serialization.Serializable

@Serializable
data class StoredTokens(val accessToken: String, val refreshToken: String)

/** Where the app keeps its tokens. The real implementation encrypts them (see EncryptedTokenStore). */
interface TokenStore {
    suspend fun read(): StoredTokens?
    suspend fun save(tokens: StoredTokens)
    suspend fun clear()
}

/** For tests and previews only. */
class InMemoryTokenStore(private var tokens: StoredTokens? = null) : TokenStore {
    override suspend fun read(): StoredTokens? = tokens
    override suspend fun save(tokens: StoredTokens) {
        this.tokens = tokens
    }
    override suspend fun clear() {
        tokens = null
    }
}
