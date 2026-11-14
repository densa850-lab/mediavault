package app.densa.mediavault.data.auth

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

/** Real Android Keystore + Tink + DataStore on a device/emulator. */
@RunWith(AndroidJUnit4::class)
class EncryptedTokenStoreTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun saveReadClear_andNoPlaintextOnDisk() = runBlocking {
        val store = EncryptedTokenStore(context)
        val tokens = StoredTokens("device-access-token-123", "device-refresh-token-456")
        store.save(tokens)
        assertEquals(tokens, store.read())
        assertEquals(tokens, EncryptedTokenStore(context).read()) // new instance, same keystore key

        val files = File(context.filesDir.parentFile, "").walkTopDown().filter { it.isFile }.toList()
        val leaked = files.filter { f ->
            val text = runCatching { f.readBytes().toString(Charsets.ISO_8859_1) }.getOrDefault("")
            text.contains("device-access-token-123") || text.contains("device-refresh-token-456")
        }
        assertFalse("plaintext token found in ${leaked.map { it.name }}", leaked.isNotEmpty())

        store.clear()
        assertNull(store.read())
    }
}
