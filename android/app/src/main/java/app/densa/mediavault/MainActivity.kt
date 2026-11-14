package app.densa.mediavault

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewmodel.compose.viewModel
import app.densa.mediavault.ui.auth.AuthRoute
import app.densa.mediavault.ui.auth.AuthViewModel
import app.densa.mediavault.ui.home.HomeRoute
import app.densa.mediavault.ui.home.HomeViewModel
import app.densa.mediavault.ui.theme.MediaVaultTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as MediaVaultApp).container
        setContent {
            MediaVaultTheme {
                // Two screens, so a saveable flag is enough (no navigation library yet).
                var showAccount by rememberSaveable { mutableStateOf(false) }
                if (showAccount) {
                    BackHandler { showAccount = false }
                    val authVm: AuthViewModel = viewModel(
                        factory = AuthViewModel.factory(container.authRepository),
                    )
                    AuthRoute(viewModel = authVm, onBack = { showAccount = false })
                } else {
                    val vm: HomeViewModel = viewModel(
                        factory = HomeViewModel.factory(container.healthRepository),
                    )
                    HomeRoute(
                        viewModel = vm,
                        serverUrl = container.apiBaseUrl,
                        showErrorReason = BuildConfig.DEBUG,
                        onAccountClick = { showAccount = true },
                    )
                }
            }
        }
    }
}
