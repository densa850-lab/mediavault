package app.densa.mediavault.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.densa.mediavault.data.remote.HealthDto
import app.densa.mediavault.data.repository.HealthRepository
import app.densa.mediavault.data.repository.HealthResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface HomeUiState {
    data object Loading : HomeUiState
    data class Connected(val health: HealthDto) : HomeUiState
    data class Degraded(val health: HealthDto) : HomeUiState
    data class Error(val reason: String) : HomeUiState
}

class HomeViewModel(private val repository: HealthRepository) : ViewModel() {
    private val _state = MutableStateFlow<HomeUiState>(HomeUiState.Loading)
    val state: StateFlow<HomeUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        _state.value = HomeUiState.Loading
        viewModelScope.launch {
            _state.value = when (val r = repository.check()) {
                is HealthResult.Healthy -> HomeUiState.Connected(r.health)
                is HealthResult.Degraded -> HomeUiState.Degraded(r.health)
                is HealthResult.Unreachable -> HomeUiState.Error(r.reason)
            }
        }
    }

    companion object {
        fun factory(repository: HealthRepository): ViewModelProvider.Factory = viewModelFactory {
            initializer { HomeViewModel(repository) }
        }
    }
}
