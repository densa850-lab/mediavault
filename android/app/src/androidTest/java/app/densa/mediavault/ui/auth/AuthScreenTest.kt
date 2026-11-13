package app.densa.mediavault.ui.auth

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.compose.ui.text.AnnotatedString
import app.densa.mediavault.ui.theme.MediaVaultTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AuthScreenTest {
    @get:Rule
    val rule = createComposeRule()

    private val submitted = mutableListOf<Pair<String, String>>()
    private val modes = mutableListOf<AuthMode>()
    private var logouts = 0

    private fun show(state: AuthUiState) {
        rule.setContent {
            MediaVaultTheme {
                AuthScreen(
                    state = state,
                    onBack = {},
                    onSubmit = { e, p -> submitted += e to p },
                    onModeChange = { modes += it },
                    onLogout = { logouts++ },
                )
            }
        }
    }

    @Test
    fun login_submitsEmailAndPassword() {
        show(AuthUiState.SignedOut())
        rule.onNodeWithTag("email_field").performTextInput("a@example.com")
        rule.onNodeWithTag("password_field").performTextInput("correct-horse-battery")
        rule.onNodeWithTag("auth_submit").performClick()
        rule.waitForIdle()
        assertEquals(listOf("a@example.com" to "correct-horse-battery"), submitted)
    }

    @Test
    fun password_isMasked() {
        show(AuthUiState.SignedOut())
        rule.onNodeWithTag("password_field").performTextInput("secret-password-1")
        // What is rendered (EditableText) is the bullet mask, never the password itself.
        rule.onNodeWithTag("password_field").assert(
            SemanticsMatcher.expectValue(
                SemanticsProperties.EditableText,
                AnnotatedString("\u2022".repeat("secret-password-1".length)),
            ),
        )
    }

    @Test
    fun register_shortPassword_showsErrorAndDoesNotSubmit() {
        show(AuthUiState.SignedOut(mode = AuthMode.Register))
        rule.onNodeWithTag("email_field").performTextInput("a@example.com")
        rule.onNodeWithTag("password_field").performTextInput("short")
        rule.onNodeWithTag("auth_submit").performClick()
        rule.onNodeWithText("Password must be at least 12 characters.").assertIsDisplayed()
        assertEquals(emptyList<Pair<String, String>>(), submitted)
    }

    @Test
    fun serverError_isShown() {
        show(AuthUiState.SignedOut(error = "Invalid email or password."))
        rule.onNodeWithTag("auth_error").assertIsDisplayed()
        rule.onNodeWithText("Invalid email or password.").assertIsDisplayed()
    }

    @Test
    fun switchToRegister_callsBack() {
        show(AuthUiState.SignedOut())
        rule.onNodeWithText("Create an account").performClick()
        rule.waitForIdle()
        assertEquals(listOf(AuthMode.Register), modes)
    }

    @Test
    fun signedIn_showsEmail_andSignsOut() {
        show(AuthUiState.SignedIn("a@example.com"))
        rule.onNodeWithText("Signed in as a@example.com").assertIsDisplayed()
        rule.onNodeWithText("Sign out").performClick()
        rule.waitForIdle()
        assertEquals(1, logouts)
    }
}
