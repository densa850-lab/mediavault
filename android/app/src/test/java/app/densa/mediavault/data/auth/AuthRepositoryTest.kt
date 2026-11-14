package app.densa.mediavault.data.auth

import app.densa.mediavault.data.remote.NetworkModule
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Real Retrofit + OkHttp against MockWebServer, with an in-memory token store. */
class AuthRepositoryTest {
    private lateinit var server: MockWebServer
    private lateinit var store: InMemoryTokenStore
    private lateinit var repo: NetworkAuthRepository

    private fun tokens(access: String, refresh: String) =
        """{"access_token":"$access","token_type":"bearer","expires_in":900,
           "refresh_token":"$refresh","refresh_expires_in":2592000}"""

    private val user = """{"id":"u1","email":"a@example.com","is_active":true,"created_at":"2026-11-14T00:00:00Z"}"""

    private fun respond(code: Int, body: String = "") =
        server.enqueue(MockResponse.Builder().code(code).body(body).build())

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        store = InMemoryTokenStore()
        repo = NetworkAuthRepository(NetworkModule.createAuthApi(server.url("/").toString()), store)
    }

    @After
    fun tearDown() = server.close()

    @Test
    fun login_success_storesTokens_andSendsCredentials() = runTest {
        respond(200, tokens("acc-1", "ref-1"))
        assertEquals(AuthOutcome.Success, repo.login(" a@example.com ", "correct-horse-battery"))
        assertEquals(StoredTokens("acc-1", "ref-1"), store.read())
        val req = server.takeRequest()
        assertEquals("/api/v1/auth/login", req.url.encodedPath)
        val body = req.body!!.utf8()
        assertTrue(body.contains("\"email\":\"a@example.com\""))
    }

    @Test
    fun login_wrongCredentials_isGeneric_andStoresNothing() = runTest {
        respond(401, """{"detail":"Invalid email or password."}""")
        assertEquals(AuthOutcome.Failure("Invalid email or password."), repo.login("a@example.com", "nope-nope-nope"))
        assertNull(store.read())
    }

    @Test
    fun login_rateLimited() = runTest {
        respond(429, """{"detail":"Too many attempts. Try again later."}""")
        assertEquals(AuthOutcome.Failure("Too many attempts. Try again later."), repo.login("a@example.com", "x"))
    }

    @Test
    fun login_serverDown_isUnreachable() = runTest {
        server.close()
        val r = repo.login("a@example.com", "correct-horse-battery")
        assertEquals(AuthOutcome.Failure(NetworkAuthRepository.UNREACHABLE), r)
    }

    @Test
    fun register_shortPassword_rejectedLocally() = runTest {
        val r = repo.register("a@example.com", "short")
        assertTrue((r as AuthOutcome.Failure).message.contains("12"))
        assertEquals(0, server.requestCount)
    }

    @Test
    fun register_accepted() = runTest {
        respond(202, """{"detail":"If this email can be used, the account is ready. Sign in to continue."}""")
        assertEquals(AuthOutcome.Success, repo.register("a@example.com", "correct-horse-battery"))
    }

    @Test
    fun register_validationMessage_fromServer() = runTest {
        respond(422, """{"detail":[{"type":"value_error","msg":"Value error, Password must not be only whitespace."}]}""")
        assertEquals(
            AuthOutcome.Failure("Password must not be only whitespace."),
            repo.register("a@example.com", "            "),
        )
    }

    @Test
    fun currentSession_signedOut_withoutTokens() = runTest {
        assertEquals(SessionState.SignedOut, repo.currentSession())
        assertEquals(0, server.requestCount)
    }

    @Test
    fun currentSession_sendsBearer() = runTest {
        store.save(StoredTokens("acc-1", "ref-1"))
        respond(200, user)
        assertEquals("a@example.com", (repo.currentSession() as SessionState.SignedIn).user.email)
        assertEquals("Bearer acc-1", server.takeRequest().headers["Authorization"])
    }

    @Test
    fun currentSession_expiredAccess_rotatesRefresh_andRetries() = runTest {
        store.save(StoredTokens("old", "ref-1"))
        respond(401, """{"detail":"Not authenticated."}""")
        respond(200, tokens("acc-2", "ref-2"))
        respond(200, user)
        assertTrue(repo.currentSession() is SessionState.SignedIn)
        assertEquals(StoredTokens("acc-2", "ref-2"), store.read())
        server.takeRequest()
        val refresh = server.takeRequest()
        assertEquals("/api/v1/auth/refresh", refresh.url.encodedPath)
        assertTrue(refresh.body!!.utf8().contains("\"refresh_token\":\"ref-1\""))
        assertEquals("Bearer acc-2", server.takeRequest().headers["Authorization"])
    }

    @Test
    fun currentSession_refreshRejected_clearsTokens() = runTest {
        store.save(StoredTokens("old", "reused"))
        respond(401, "{}")
        respond(401, """{"detail":"Session expired. Sign in again."}""")
        assertEquals(SessionState.SignedOut, repo.currentSession())
        assertNull(store.read())
    }

    @Test
    fun currentSession_serverDown_keepsTokens() = runTest {
        store.save(StoredTokens("acc-1", "ref-1"))
        server.close()
        assertTrue(repo.currentSession() is SessionState.Unavailable)
        assertEquals(StoredTokens("acc-1", "ref-1"), store.read())
    }

    @Test
    fun logout_revokesOnServer_andClears() = runTest {
        store.save(StoredTokens("acc-1", "ref-1"))
        respond(204)
        repo.logout()
        assertNull(store.read())
        val req = server.takeRequest()
        assertEquals("/api/v1/auth/logout", req.url.encodedPath)
        assertEquals("Bearer acc-1", req.headers["Authorization"])
        assertTrue(req.body!!.utf8().contains("\"refresh_token\":\"ref-1\""))
    }

    @Test
    fun logout_serverDown_stillClearsLocally() = runTest {
        store.save(StoredTokens("acc-1", "ref-1"))
        server.close()
        repo.logout()
        assertNull(store.read())
    }
}
