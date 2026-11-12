package app.densa.mediavault.ui.home

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.densa.mediavault.data.remote.HealthChecksDto
import app.densa.mediavault.data.remote.HealthDto
import app.densa.mediavault.ui.theme.MediaVaultTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HomeScreenTest {
    @get:Rule
    val rule = createComposeRule()

    private val dto = HealthDto("ok", "mediavault-api", "0.1.0", "test", HealthChecksDto("ok"), "t")

    @Test
    fun connectedState_showsDetails() {
        rule.setContent { MediaVaultTheme { HomeScreen(HomeUiState.Connected(dto), "http://10.0.2.2:8000/") {} } }
        rule.onNodeWithText("Backend connected").assertIsDisplayed()
        rule.onNodeWithText("mediavault-api").assertIsDisplayed()
    }

    @Test
    fun errorState_retryButtonCallsBack() {
        var retries = 0
        rule.setContent {
            MediaVaultTheme { HomeScreen(HomeUiState.Error("refused"), "http://10.0.2.2:8000/") { retries++ } }
        }
        rule.onNodeWithText("Backend unreachable").assertIsDisplayed()
        rule.onNodeWithText("Check again").performClick()
        assertEquals(1, retries)
    }
}
