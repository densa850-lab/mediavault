package app.densa.mediavault.ui.home

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
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
    // v2 rule (StandardTestDispatcher) replaces the deprecated junit4.createComposeRule (MV-014).
    @get:Rule
    val rule = createComposeRule()

    private val server = "http://10.0.2.2:8000/"
    private val dto = HealthDto("ok", "mediavault-api", "0.1.0", "test", HealthChecksDto("ok"), "t")
    private val degradedDto = dto.copy(status = "degraded", checks = HealthChecksDto("error"))

    private fun show(state: HomeUiState, showErrorReason: Boolean = false, onRetry: () -> Unit = {}) {
        rule.setContent {
            MediaVaultTheme { HomeScreen(state, server, showErrorReason = showErrorReason, onRetry = onRetry) }
        }
    }

    @Test
    fun connectedState_showsDetails() {
        show(HomeUiState.Connected(dto))
        rule.onNodeWithText("Backend connected").assertIsDisplayed()
        rule.onNodeWithText("mediavault-api").assertIsDisplayed()
    }

    @Test
    fun errorState_retryButtonCallsBack() {
        var retries = 0
        show(HomeUiState.Error("refused")) { retries++ }
        rule.onNodeWithText("Backend unreachable").assertIsDisplayed()
        rule.onNodeWithText("Check again").performClick()
        rule.waitForIdle()
        assertEquals(1, retries)
    }

    @Test
    fun loadingState_showsProgressAndNoRetryButton() {
        show(HomeUiState.Loading)
        rule.onNodeWithText("Checking the MediaVault server…").assertIsDisplayed()
        rule.onAllNodesWithText("Check again").assertCountEquals(0)
        rule.onAllNodesWithText("Backend connected").assertCountEquals(0)
    }

    @Test
    fun degradedState_showsDatabaseErrorAndRetry() {
        var retries = 0
        show(HomeUiState.Degraded(degradedDto)) { retries++ }
        rule.onNodeWithText("Backend reachable, database unavailable").assertIsDisplayed()
        rule.onNodeWithText("Error").assertIsDisplayed()
        rule.onNodeWithText("Check again").performClick()
        rule.waitForIdle()
        assertEquals(1, retries)
    }

    @Test
    fun errorState_debugShowsReason() {
        show(HomeUiState.Error("Failed to connect to /10.0.2.2:8000"), showErrorReason = true)
        rule.onNodeWithTag("error_reason").assertIsDisplayed()
        rule.onNodeWithText("Reason (debug build): Failed to connect to /10.0.2.2:8000").assertIsDisplayed()
    }

    @Test
    fun errorState_releaseHidesReason() {
        show(HomeUiState.Error("Failed to connect to /10.0.2.2:8000"), showErrorReason = false)
        rule.onAllNodesWithTag("error_reason").assertCountEquals(0)
    }
}
