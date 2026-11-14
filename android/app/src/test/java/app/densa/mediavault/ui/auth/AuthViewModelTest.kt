package app.densa.mediavault.ui.auth

import app.densa.mediavault.data.auth.AuthOutcome
import app.densa.mediavault.data.auth.AuthRepository
import app.densa.mediavault.data.auth.SessionState
import app.densa.mediavault.data.auth.UserDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AuthViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    private class FakeRepo : AuthRepository {
        var session: SessionState = SessionState.SignedOut
        var loginResult: AuthOutcome = AuthOutcome.Success
        var registerResult: AuthOutcome = AuthOutcome.Success
        var loggedOut = false
        override suspend fun register(email: String, password: String) = registerResult
        override suspend fun login(email: String, password: String): AuthOutcome {
            if (loginResult == AuthOutcome.Success) session = SessionState.SignedIn(UserDto("u1", email))
            return loginResult
        }
        override suspend fun currentSession() = session
        override suspend fun logout() {
            loggedOut = true
            session = SessionState.SignedOut
        }
    }

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun startsChecking_thenSignedOut() = runTest(dispatcher) {
        val vm = AuthViewModel(FakeRepo())
        assertEquals(AuthUiState.Checking, vm.state.value)
        advanceUntilIdle()
        assertEquals(AuthUiState.SignedOut(), vm.state.value)
    }

    @Test
    fun existingSession_isSignedIn() = runTest(dispatcher) {
        val repo = FakeRepo().apply { session = SessionState.SignedIn(UserDto("u1", "a@example.com")) }
        val vm = AuthViewModel(repo)
        advanceUntilIdle()
        assertEquals(AuthUiState.SignedIn("a@example.com"), vm.state.value)
    }

    @Test
    fun login_success_thenLogout() = runTest(dispatcher) {
        val repo = FakeRepo()
        val vm = AuthViewModel(repo)
        advanceUntilIdle()
        vm.submit("a@example.com", "correct-horse-battery")
        assertTrue((vm.state.value as AuthUiState.SignedOut).busy)
        advanceUntilIdle()
        assertEquals(AuthUiState.SignedIn("a@example.com"), vm.state.value)
        vm.logout()
        advanceUntilIdle()
        assertTrue(repo.loggedOut)
        assertEquals(AuthUiState.SignedOut(), vm.state.value)
    }

    @Test
    fun login_failure_showsError() = runTest(dispatcher) {
        val repo = FakeRepo().apply { loginResult = AuthOutcome.Failure("Invalid email or password.") }
        val vm = AuthViewModel(repo)
        advanceUntilIdle()
        vm.submit("a@example.com", "bad")
        advanceUntilIdle()
        assertEquals(AuthUiState.SignedOut(error = "Invalid email or password."), vm.state.value)
    }

    @Test
    fun register_success_switchesToLoginWithNotice() = runTest(dispatcher) {
        val vm = AuthViewModel(FakeRepo())
        advanceUntilIdle()
        vm.setMode(AuthMode.Register)
        vm.submit("a@example.com", "correct-horse-battery")
        advanceUntilIdle()
        val s = vm.state.value as AuthUiState.SignedOut
        assertEquals(AuthMode.Login, s.mode)
        assertEquals("Account ready. Sign in to continue.", s.notice)
    }

    @Test
    fun serverUnavailable_isRetryable_notSignedOut() = runTest(dispatcher) {
        val repo = FakeRepo().apply { session = SessionState.Unavailable("down") }
        val vm = AuthViewModel(repo)
        advanceUntilIdle()
        assertEquals(AuthUiState.Unavailable("down"), vm.state.value)
        // Retry once the server is back: the kept session is still there.
        repo.session = SessionState.SignedIn(app.densa.mediavault.data.auth.UserDto("u1", "a@example.com"))
        vm.loadSession()
        advanceUntilIdle()
        assertEquals(AuthUiState.SignedIn("a@example.com"), vm.state.value)
    }
}
