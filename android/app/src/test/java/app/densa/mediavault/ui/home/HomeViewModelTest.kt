package app.densa.mediavault.ui.home

import app.densa.mediavault.data.remote.HealthChecksDto
import app.densa.mediavault.data.remote.HealthDto
import app.densa.mediavault.data.repository.HealthRepository
import app.densa.mediavault.data.repository.HealthResult
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
class HomeViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    private val dto = HealthDto("ok", "mediavault-api", "0.1.0", "test", HealthChecksDto("ok"), "t")

    private class FakeRepo(var results: ArrayDeque<HealthResult>) : HealthRepository {
        var calls = 0
        override suspend fun check(): HealthResult {
            calls++
            return results.removeFirst()
        }
    }

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun startsLoading_thenConnected() = runTest(dispatcher) {
        val vm = HomeViewModel(FakeRepo(ArrayDeque(listOf(HealthResult.Healthy(dto)))))
        assertEquals(HomeUiState.Loading, vm.state.value)
        advanceUntilIdle()
        assertEquals(HomeUiState.Connected(dto), vm.state.value)
    }

    @Test
    fun degradedResult_mapsToDegraded() = runTest(dispatcher) {
        val degraded = dto.copy(status = "degraded", checks = HealthChecksDto("error"))
        val vm = HomeViewModel(FakeRepo(ArrayDeque(listOf(HealthResult.Degraded(degraded)))))
        advanceUntilIdle()
        assertTrue(vm.state.value is HomeUiState.Degraded)
    }

    @Test
    fun error_thenRetry_recovers() = runTest(dispatcher) {
        val repo = FakeRepo(
            ArrayDeque(listOf(HealthResult.Unreachable("refused"), HealthResult.Healthy(dto))),
        )
        val vm = HomeViewModel(repo)
        advanceUntilIdle()
        assertEquals(HomeUiState.Error("refused"), vm.state.value)
        vm.refresh()
        assertEquals(HomeUiState.Loading, vm.state.value)
        advanceUntilIdle()
        assertEquals(HomeUiState.Connected(dto), vm.state.value)
        assertEquals(2, repo.calls)
    }
}
