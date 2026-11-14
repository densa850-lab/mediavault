package app.densa.mediavault.data.auth

import app.densa.mediavault.data.remote.NetworkModule
import java.io.IOException
import kotlinx.coroutines.test.runTest
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Response

/**
 * MV-023 / MV-024 (Tester's re-gate of PR #4): only a definitive 401/422 on refresh signs the user
 * out. 429, 5xx and network errors are temporary: tokens and session are kept.
 */
class AuthRepositoryTemporaryFailureTest {
    private lateinit var server: MockWebServer
    private lateinit var store: InMemoryTokenStore
    private lateinit var repo: NetworkAuthRepository

    private fun tokens(access: String, refresh: String) =
        """{"access_token":"$access","token_type":"bearer","expires_in":900,
           "refresh_token":"$refresh","refresh_expires_in":2592000}"""

    private val user = """{"id":"u1","email":"a@example.com"}"""

    private fun respond(code: Int, body: String = "", retryAfter: String? = null) {
        val b = MockResponse.Builder().code(code).body(body)
        if (retryAfter != null) b.addHeader("Retry-After", retryAfter)
        server.enqueue(b.build())
    }

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        store = InMemoryTokenStore()
        repo = NetworkAuthRepository(NetworkModule.createAuthApi(server.url("/").toString()), store)
    }

    @After
    fun tearDown() = server.close()

    private suspend fun assertTemporaryAndKept(state: SessionState, expected: StoredTokens) {
        assertTrue("expected Unavailable, got $state", state is SessionState.Unavailable)
        assertTrue((state as SessionState.Unavailable).message.contains("still signed in"))
        assertEquals(expected, store.read())
    }

    @Test
    fun refresh429_keepsTokens_andIsRetryable() = runTest {
        store.save(StoredTokens("old", "ref-1"))
        respond(401, "{}")
        respond(429, """{"detail":"Too many attempts. Try again later."}""", retryAfter = "60")
        assertTemporaryAndKept(repo.currentSession(), StoredTokens("old", "ref-1"))
        // Retry later: the same refresh token still works.
        respond(401, "{}")
        respond(200, tokens("acc-2", "ref-2"))
        respond(200, user)
        assertTrue(repo.currentSession() is SessionState.SignedIn)
        assertEquals(StoredTokens("acc-2", "ref-2"), store.read())
    }

    @Test
    fun refresh5xx_keepsTokens() = runTest {
        for (code in listOf(500, 502, 503)) {
            store.save(StoredTokens("old", "ref-1"))
            respond(401, "{}")
            respond(code, "")
            assertTemporaryAndKept(repo.currentSession(), StoredTokens("old", "ref-1"))
        }
    }

    @Test
    fun refresh422_isDefinitive_andClears() = runTest {
        store.save(StoredTokens("old", "garbage"))
        respond(401, "{}")
        respond(422, """{"detail":[{"type":"string_too_long","loc":["body","refresh_token"],"msg":"x"}]}""")
        assertEquals(SessionState.SignedOut, repo.currentSession())
        assertNull(store.read())
    }

    @Test
    fun meFailsTemporarilyAfterRotation_newPairIsKept() = runTest {
        store.save(StoredTokens("old", "ref-1"))
        respond(401, "{}")
        respond(200, tokens("acc-2", "ref-2"))
        respond(503, "")
        assertTemporaryAndKept(repo.currentSession(), StoredTokens("acc-2", "ref-2"))
    }

    @Test
    fun refreshNetworkError_keepsTokens() = runTest {
        val flaky = object : AuthApi {
            override suspend fun register(body: CredentialsDto): Response<Unit> = error("unused")
            override suspend fun login(body: CredentialsDto): Response<TokenDto> = error("unused")
            override suspend fun refresh(body: RefreshDto): Response<TokenDto> = throw IOException("reset")
            override suspend fun logout(bearer: String?, body: LogoutDto): Response<Unit> = error("unused")
            override suspend fun me(bearer: String): Response<UserDto> =
                Response.error(401, "{}".toResponseBody())
        }
        val s = InMemoryTokenStore()
        s.save(StoredTokens("old", "ref-1"))
        val state = NetworkAuthRepository(flaky, s).currentSession()
        assertEquals(SessionState.Unavailable(NetworkAuthRepository.UNREACHABLE), state)
        assertEquals(StoredTokens("old", "ref-1"), s.read())
    }

    /** Server model with the per-IP failed-refresh limit (30) of the API. */
    private class LimitedServer(private val blockValidToo: Boolean) : Dispatcher() {
        private var failures = 0
        private var live = "ref-1"
        private var gen = 1

        @Synchronized
        override fun dispatch(request: RecordedRequest): MockResponse {
            val body = request.body?.utf8().orEmpty()
            return when (request.url.encodedPath) {
                "/api/v1/auth/me" ->
                    if (request.headers["Authorization"] == "Bearer acc-$gen" && gen > 1) {
                        MockResponse.Builder().code(200).body("""{"id":"u1","email":"a@example.com"}""").build()
                    } else {
                        MockResponse.Builder().code(401).body("{}").build()
                    }
                else -> {
                    val presented = Regex("\"refresh_token\":\"([^\"]+)\"").find(body)!!.groupValues[1]
                    val valid = presented == live
                    if (valid && !(blockValidToo && failures >= 30)) {
                        gen++
                        live = "ref-$gen"
                        MockResponse.Builder().code(200).body(
                            """{"access_token":"acc-$gen","token_type":"bearer","expires_in":900,
                               "refresh_token":"ref-$gen","refresh_expires_in":2592000}""",
                        ).build()
                    } else {
                        if (!valid) failures++
                        if (failures > 30) {
                            MockResponse.Builder().code(429).addHeader("Retry-After", "60")
                                .body("""{"detail":"Too many attempts. Try again later."}""").build()
                        } else {
                            MockResponse.Builder().code(401).body("""{"detail":"Session expired. Sign in again."}""").build()
                        }
                    }
                }
            }
        }
    }

    private fun junkFlood(n: Int): List<Int> {
        val http = OkHttpClient()
        val json = "application/json".toMediaType()
        return (1..n).map { i ->
            val req = Request.Builder().url(server.url("/api/v1/auth/refresh"))
                .post("""{"refresh_token":"garbage-$i"}""".toRequestBody(json)).build()
            http.newCall(req).execute().use { it.code }
        }
    }

    @Test
    fun testersAttack_fixedServer_userStaysSignedIn() = runTest {
        server.dispatcher = LimitedServer(blockValidToo = false)
        store.save(StoredTokens("expired", "ref-1"))
        val codes = junkFlood(31)
        assertEquals(429, codes.last())
        val state = repo.currentSession()
        assertTrue("expected SignedIn, got $state", state is SessionState.SignedIn)
        assertEquals(StoredTokens("acc-2", "ref-2"), store.read())
    }

    @Test
    fun testersAttack_serverThat429sValidTokens_userIsNotSignedOut() = runTest {
        server.dispatcher = LimitedServer(blockValidToo = true)
        store.save(StoredTokens("expired", "ref-1"))
        junkFlood(31)
        assertTemporaryAndKept(repo.currentSession(), StoredTokens("expired", "ref-1"))
    }

    @Test
    fun logout429_isRetriedOnce_thenClears() = runTest {
        store.save(StoredTokens("acc-1", "ref-1"))
        respond(429, "{}")
        respond(204)
        repo.logout()
        assertNull(store.read())
        assertEquals(2, server.requestCount)
    }

    @Test
    fun logoutKeepsFailing_stillClearsLocally_afterTwoAttempts() = runTest {
        store.save(StoredTokens("acc-1", "ref-1"))
        respond(429, "{}")
        respond(503, "")
        repo.logout()
        assertNull(store.read())
        assertEquals(2, server.requestCount)
    }
}
