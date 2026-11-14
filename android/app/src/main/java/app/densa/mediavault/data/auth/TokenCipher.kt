package app.densa.mediavault.data.auth

import com.google.crypto.tink.Aead
import java.security.GeneralSecurityException
import java.util.Base64
import kotlinx.serialization.json.Json

/**
 * Encrypts the token pair with a Tink AEAD (AES-256-GCM). Associated data binds the ciphertext
 * to its purpose, so it cannot be swapped with another encrypted value. Pure JVM: unit-testable.
 */
class TokenCipher(private val aead: Aead) {
    fun encrypt(tokens: StoredTokens): String {
        val plain = Json.encodeToString(StoredTokens.serializer(), tokens).toByteArray(Charsets.UTF_8)
        return Base64.getEncoder().encodeToString(aead.encrypt(plain, ASSOCIATED_DATA))
    }

    /** Returns null when the value is corrupt, tampered with, or from another key. */
    fun decrypt(ciphertext: String): StoredTokens? =
        try {
            val plain = aead.decrypt(Base64.getDecoder().decode(ciphertext), ASSOCIATED_DATA)
            Json.decodeFromString(StoredTokens.serializer(), String(plain, Charsets.UTF_8))
        } catch (e: GeneralSecurityException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        }

    companion object {
        val ASSOCIATED_DATA = "app.densa.mediavault/auth-tokens/v1".toByteArray(Charsets.UTF_8)
    }
}
