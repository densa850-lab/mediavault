package app.densa.mediavault.data

import app.densa.mediavault.data.remote.NetworkModule
import app.densa.mediavault.data.repository.HealthResult
import app.densa.mediavault.data.repository.NetworkHealthRepository
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Exercises the real Retrofit 3.0.0 + kotlinx-serialization converter on top of OkHttp 5.5.1
 * against a local MockWebServer. This is the runtime proof that the pairing works.
 */
class HealthRepositoryTest {
    private lateinit var server: MockWebServer
    private lateinit var repo: NetworkHealthRepository

    private fun body(status: String, db: String) =
        """{"status":"$status","service":"mediavault-api","version":"0.1.0",
           "environment":"test","checks":{"database":"$db"},"time":"2026-11-12T16:00:00Z",
           "extra":"ignored"}"""

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        repo = NetworkHealthRepository(NetworkModule.createApi(server.url("/").toString()))
    }

    @After
    fun tearDown() {
        server.close()
    }

    @Test
    fun healthy_200_mapsToHealthy_andHitsCorrectPath() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body(body("ok", "ok")).build())
        val result = repo.check()
        assertTrue(result is HealthResult.Healthy)
        assertEquals("mediavault-api", (result as HealthResult.Healthy).health.service)
        assertEquals("/api/v1/health", server.takeRequest().url.encodedPath)
    }

    @Test
    fun degraded_503_bodyIsParsed() = runTest {
        server.enqueue(MockResponse.Builder().code(503).body(body("degraded", "error")).build())
        val result = repo.check()
        assertTrue(result is HealthResult.Degraded)
        assertEquals("error", (result as HealthResult.Degraded).health.checks.database)
    }

    @Test
    fun serverError_500_isUnreachable() = runTest {
        server.enqueue(MockResponse.Builder().code(500).body("oops").build())
        val result = repo.check()
        assertEquals(HealthResult.Unreachable("HTTP 500"), result)
    }

    @Test
    fun malformedJson_isUnreachable() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body("{not json").build())
        assertTrue(repo.check() is HealthResult.Unreachable)
    }

    @Test
    fun connectionRefused_isUnreachable() = runTest {
        val url = server.url("/").toString()
        server.close()
        val offline = NetworkHealthRepository(NetworkModule.createApi(url))
        assertTrue(offline.check() is HealthResult.Unreachable)
    }
}
