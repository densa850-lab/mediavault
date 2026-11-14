package app.densa.mediavault.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.densa.mediavault.data.auth.AuthOutcome
import app.densa.mediavault.data.auth.AuthRepository
import app.densa.mediavault.data.auth.SessionState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

enum class AuthMode { Login, Register }

sealed interface AuthUiState {
    data object Checking : AuthUiState
    data class SignedOut(
        val mode: AuthMode = AuthMode.Login,
        val busy: Boolean = false,
        val error: String? = null,
        val notice: String? = null,
    ) : AuthUiState
    data class SignedIn(val email: String) : AuthUiState

    /** The session could not be checked right now (busy / offline). Tokens are kept; retry. */
    data class Unavailable(val message: String) : AuthUiState
}

class AuthViewModel(private val repository: AuthRepository) : ViewModel() {
    private val _state = MutableStateFlow<AuthUiState>(AuthUiState.Checking)
    val state: StateFlow<AuthUiState> = _state.asStateFlow()

    init {
        loadSession()
    }

    fun loadSession() {
        viewModelScope.launch {
            if (_state.value is AuthUiState.Unavailable) _state.value = AuthUiState.Checking
            _state.value = when (val s = repository.currentSession()) {
                is SessionState.SignedIn -> AuthUiState.SignedIn(s.user.email)
                SessionState.SignedOut -> AuthUiState.SignedOut()
                is SessionState.Unavailable -> AuthUiState.Unavailable(s.message)
            }
        }
    }

    fun setMode(mode: AuthMode) {
        _state.value = AuthUiState.SignedOut(mode = mode)
    }

    fun submit(email: String, password: String) {
        val current = _state.value as? AuthUiState.SignedOut ?: return
        if (current.busy) return
        _state.value = current.copy(busy = true, error = null, notice = null)
        viewModelScope.launch {
            when (current.mode) {
                AuthMode.Login -> when (val r = repository.login(email, password)) {
                    AuthOutcome.Success -> loadSession()
                    is AuthOutcome.Failure -> _state.value = current.copy(busy = false, error = r.message)
                }
                AuthMode.Register -> when (val r = repository.register(email, password)) {
                    AuthOutcome.Success -> _state.value = AuthUiState.SignedOut(
                        mode = AuthMode.Login,
                        notice = "Account ready. Sign in to continue.",
                    )
                    is AuthOutcome.Failure -> _state.value = current.copy(busy = false, error = r.message)
                }
            }
        }
    }

    fun logout() {
        viewModelScope.launch {
            repository.logout()
            _state.value = AuthUiState.SignedOut()
        }
    }

    companion object {
        fun factory(repository: AuthRepository): ViewModelProvider.Factory = viewModelFactory {
            initializer { AuthViewModel(repository) }
        }
    }
}
