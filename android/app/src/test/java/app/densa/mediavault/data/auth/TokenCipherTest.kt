package app.densa.mediavault.data.auth

import com.google.crypto.tink.Aead
import com.google.crypto.tink.KeysetHandle
import com.google.crypto.tink.RegistryConfiguration
import com.google.crypto.tink.aead.AeadConfig
import com.google.crypto.tink.aead.PredefinedAeadParameters
import java.util.Base64
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.BeforeClass
import org.junit.Test

/** Tink AES-256-GCM on the JVM (the Android Keystore wrapping is covered by the device test). */
class TokenCipherTest {
    companion object {
        @BeforeClass
        @JvmStatic
        fun register() = AeadConfig.register()
    }

    @Suppress("DEPRECATION") // Tink 1.24 marks both generateNew overloads deprecated; fine for a test keyset.
    private fun newAead(): Aead =
        KeysetHandle.generateNew(PredefinedAeadParameters.AES256_GCM)
            .getPrimitive(RegistryConfiguration.get(), Aead::class.java)

    private val tokens = StoredTokens("access-token-value", "refresh-token-value")

    @Test
    fun roundTrip() {
        val cipher = TokenCipher(newAead())
        assertEquals(tokens, cipher.decrypt(cipher.encrypt(tokens)))
    }

    @Test
    fun ciphertextDoesNotContainTokens_andIsRandomised() {
        val cipher = TokenCipher(newAead())
        val a = cipher.encrypt(tokens)
        val decoded = String(Base64.getDecoder().decode(a), Charsets.ISO_8859_1)
        assertFalse(decoded.contains("access-token-value"))
        assertFalse(decoded.contains("refresh-token-value"))
        assertNotEquals(a, cipher.encrypt(tokens))
    }

    @Test
    fun tamperedCiphertext_isRejected() {
        val cipher = TokenCipher(newAead())
        val bytes = Base64.getDecoder().decode(cipher.encrypt(tokens))
        bytes[bytes.size - 1] = (bytes[bytes.size - 1].toInt() xor 1).toByte()
        assertNull(cipher.decrypt(Base64.getEncoder().encodeToString(bytes)))
        assertNull(cipher.decrypt("not base64 !!"))
    }

    @Test
    fun otherKey_cannotDecrypt() {
        val ct = TokenCipher(newAead()).encrypt(tokens)
        assertNull(TokenCipher(newAead()).decrypt(ct))
    }

    @Test
    fun associatedData_isEnforced() {
        val aead = newAead()
        val wrongAd = Base64.getEncoder().encodeToString(
            aead.encrypt("{}".toByteArray(), "something-else".toByteArray()),
        )
        assertNull(TokenCipher(aead).decrypt(wrongAd))
    }
}
