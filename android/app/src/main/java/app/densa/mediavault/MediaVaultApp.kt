package app.densa.mediavault

import android.app.Application
import app.densa.mediavault.data.auth.AuthRepository
import app.densa.mediavault.data.auth.EncryptedTokenStore
import app.densa.mediavault.data.auth.NetworkAuthRepository
import app.densa.mediavault.data.auth.TokenStore
import app.densa.mediavault.data.remote.NetworkModule
import app.densa.mediavault.data.repository.HealthRepository
import app.densa.mediavault.data.repository.NetworkHealthRepository

/** Manual dependency container. Hilt can replace this once there is more to wire. */
class AppContainer(baseUrl: String, tokenStore: TokenStore) {
    val apiBaseUrl: String = baseUrl
    val healthRepository: HealthRepository =
        NetworkHealthRepository(NetworkModule.createApi(baseUrl))
    val authRepository: AuthRepository =
        NetworkAuthRepository(NetworkModule.createAuthApi(baseUrl), tokenStore)
}

class MediaVaultApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(BuildConfig.API_BASE_URL, EncryptedTokenStore(this))
    }
}
