package app.densa.mediavault.data

import app.densa.mediavault.data.remote.NetworkModule
import app.densa.mediavault.data.repository.HealthResult
import app.densa.mediavault.data.repository.NetworkHealthRepository
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/**
 * Optional integration test: runs the app's real network stack against a running backend.
 * Skipped unless MEDIAVAULT_LIVE_API_URL is set, e.g.
 *   MEDIAVAULT_LIVE_API_URL=http://localhost:8000/ ./gradlew testDebugUnitTest
 */
class LiveBackendHealthTest {
    @Test
    fun liveBackend_reportsHealthy() = runTest {
        val url = System.getenv("MEDIAVAULT_LIVE_API_URL")
        assumeTrue("MEDIAVAULT_LIVE_API_URL not set", !url.isNullOrBlank())
        val result = NetworkHealthRepository(NetworkModule.createApi(url!!)).check()
        assertTrue("Expected Healthy but got $result", result is HealthResult.Healthy)
    }
}
