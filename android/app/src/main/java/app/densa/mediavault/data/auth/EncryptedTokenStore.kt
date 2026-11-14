package app.densa.mediavault.data.auth

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.google.crypto.tink.Aead
import com.google.crypto.tink.KeyTemplates
import com.google.crypto.tink.RegistryConfiguration
import com.google.crypto.tink.aead.AeadConfig
import com.google.crypto.tink.integration.android.AndroidKeysetManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext

private val Context.authDataStore: DataStore<Preferences> by preferencesDataStore(name = "mv_auth")
private val TOKENS = stringPreferencesKey("tokens_v1")

/**
 * Tokens are stored in Jetpack DataStore only as Tink AES-256-GCM ciphertext. The Tink keyset is
 * itself encrypted by a non-exportable AES key in the Android Keystore, so the tokens cannot be
 * read from a copied data directory. Backups are disabled for the app (allowBackup=false).
 * (EncryptedSharedPreferences is deprecated, hence DataStore + Tink.)
 */
class EncryptedTokenStore(context: Context) : TokenStore {
    private val appContext = context.applicationContext
    private val cipher: TokenCipher by lazy { TokenCipher(createAead(appContext)) }

    override suspend fun read(): StoredTokens? = withContext(Dispatchers.IO) {
        val value = appContext.authDataStore.data.first()[TOKENS] ?: return@withContext null
        cipher.decrypt(value) ?: run {
            clear() // unreadable (e.g. keystore key lost): treat as signed out
            null
        }
    }

    override suspend fun save(tokens: StoredTokens) {
        withContext(Dispatchers.IO) {
            val encrypted = cipher.encrypt(tokens)
            appContext.authDataStore.edit { it[TOKENS] = encrypted }
        }
    }

    override suspend fun clear() {
        withContext(Dispatchers.IO) { appContext.authDataStore.edit { it.remove(TOKENS) } }
    }

    private companion object {
        const val KEYSET_NAME = "mv_auth_keyset"
        const val KEYSET_PREFS = "mv_auth_keyset_prefs"
        const val MASTER_KEY_URI = "android-keystore://mv_auth_master_key"

        fun createAead(context: Context): Aead {
            AeadConfig.register()
            return AndroidKeysetManager.Builder()
                .withSharedPref(context, KEYSET_NAME, KEYSET_PREFS)
                .withKeyTemplate(KeyTemplates.get("AES256_GCM"))
                .withMasterKeyUri(MASTER_KEY_URI)
                .build()
                .keysetHandle
                .getPrimitive(RegistryConfiguration.get(), Aead::class.java)
        }
    }
}
