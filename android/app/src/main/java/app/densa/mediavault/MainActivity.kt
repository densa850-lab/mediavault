package app.densa.mediavault

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.viewmodel.compose.viewModel
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
                val vm: HomeViewModel = viewModel(
                    factory = HomeViewModel.factory(container.healthRepository),
                )
                HomeRoute(viewModel = vm, serverUrl = container.apiBaseUrl)
            }
        }
    }
}
