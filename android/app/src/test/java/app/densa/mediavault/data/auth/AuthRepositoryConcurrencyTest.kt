package app.densa.mediavault.data.auth

import app.densa.mediavault.data.remote.NetworkModule
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Overlapping currentSession()/logout() calls on real threads against a MockWebServer that models
 * the API's STRICT protocol (no grace): presenting an already-used refresh token revokes the
 * session. So these tests fail if the client ever sends the same refresh token twice.
 */
class AuthRepositoryConcurrencyTest {
    private lateinit var server: MockWebServer

    /** Minimal server model: single-use refresh tokens with reuse detection. */
    private class Model : Dispatcher() {
        @Volatile var revoked = false
        @Volatile var rejectRefresh = false
        val refreshCalls = AtomicInteger()
        val logoutBodies = mutableListOf<String>()
        private val used = mutableSetOf<String>()
        private var live = "ref-0"
        private val validAccess = mutableSetOf<String>()
        private var gen = 0

        @Synchronized
        override fun dispatch(request: RecordedRequest): MockResponse {
            val path = request.url.encodedPath
            val body = request.body?.utf8().orEmpty()
            return when (path) {
                "/api/v1/auth/me" -> {
                    val token = request.headers["Authorization"]?.removePrefix("Bearer ")
                    if (!revoked && token in validAccess) {
                        ok("""{"id":"u1","email":"a@example.com"}""")
                    } else {
                        MockResponse.Builder().code(401).body("""{"detail":"Not authenticated."}""").build()
                    }
                }
                "/api/v1/auth/refresh" -> {
                    refreshCalls.incrementAndGet()
                    val presented = Regex("\"refresh_token\":\"([^\"]+)\"").find(body)!!.groupValues[1]
                    when {
                        rejectRefresh || revoked -> reject()
                        presented in used -> {
                            revoked = true // reuse detection
                            reject()
                        }
                        presented != live -> reject()
                        else -> {
                            used += presented
                            gen++
                            live = "ref-$gen"
                            validAccess += "acc-$gen"
                            ok(
                                """{"access_token":"acc-$gen","token_type":"bearer","expires_in":900,
                                   "refresh_token":"ref-$gen","refresh_expires_in":2592000}""",
                                delayMs = 300, // keep the refresh in flight while others arrive
                            )
                        }
                    }
                }
                "/api/v1/auth/logout" -> {
                    logoutBodies += body
                    revoked = true
                    MockResponse.Builder().code(204).build()
                }
                else -> MockResponse.Builder().code(404).build()
            }
        }

        private fun ok(json: String, delayMs: Long = 0) =
            MockResponse.Builder().code(200).body(json).headersDelay(delayMs, TimeUnit.MILLISECONDS).build()

        private fun reject() = MockResponse.Builder().code(401).body("""{"detail":"Session expired. Sign in again."}""").build()
    }

    /** Store that is slow and records overlapping writes (to catch unsynchronised updates). */
    private class SlowStore(initial: StoredTokens?) : TokenStore {
        private val inner = InMemoryTokenStore(initial)
        private val active = AtomicInteger()
        val maxConcurrentWrites = AtomicInteger()
        override suspend fun read(): StoredTokens? = inner.read()
        override suspend fun save(tokens: StoredTokens) = write { inner.save(tokens) }
        override suspend fun clear() = write { inner.clear() }
        private suspend fun write(block: suspend () -> Unit) {
            val now = active.incrementAndGet()
            maxConcurrentWrites.accumulateAndGet(now) { a, b -> maxOf(a, b) }
            delay(50)
            block()
            active.decrementAndGet()
        }
    }

    private val model = Model()

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher = model
        server.start()
    }

    @After
    fun tearDown() = server.close()

    private fun repo(store: TokenStore) =
        NetworkAuthRepository(NetworkModule.createAuthApi(server.url("/").toString()), store)

    @Test
    fun twoConcurrentSessionChecks_shareOneRefresh_andKeepTheSession() = runBlocking {
        val store = SlowStore(StoredTokens("acc-expired", "ref-0"))
        val repo = repo(store)
        val results = withContext(Dispatchers.IO) {
            listOf(async { repo.currentSession() }, async { repo.currentSession() }).awaitAll()
        }
        results.forEach { assertTrue("got $it", it is SessionState.SignedIn) }
        assertEquals(1, model.refreshCalls.get())
        assertFalse("session must not be revoked", model.revoked)
        assertEquals(StoredTokens("acc-1", "ref-1"), store.read())
        assertEquals(1, store.maxConcurrentWrites.get())
    }

    @Test
    fun manyConcurrentSessionChecks_neverPresentTheSameRefreshTokenTwice() = runBlocking {
        val store = SlowStore(StoredTokens("acc-expired", "ref-0"))
        val repo = repo(store)
        val results = withContext(Dispatchers.IO) { (1..6).map { async { repo.currentSession() } }.awaitAll() }
        results.forEach { assertTrue("got $it", it is SessionState.SignedIn) }
        assertEquals(1, model.refreshCalls.get())
        assertFalse(model.revoked)
        assertEquals(StoredTokens("acc-1", "ref-1"), store.read())
        assertEquals(1, store.maxConcurrentWrites.get())
    }

    @Test
    fun rejectedRefresh_duringConcurrentChecks_clearsCredentials() = runBlocking {
        model.rejectRefresh = true
        val store = SlowStore(StoredTokens("acc-expired", "ref-0"))
        val repo = repo(store)
        val results = withContext(Dispatchers.IO) {
            listOf(async { repo.currentSession() }, async { repo.currentSession() }).awaitAll()
        }
        results.forEach { assertEquals(SessionState.SignedOut, it) }
        assertNull(store.read())
        assertEquals(1, model.refreshCalls.get()) // the second caller saw the cleared store
    }

    @Test
    fun logoutDuringRefresh_waits_revokesTheNewestPair_andLeavesNoCredentials() = runBlocking {
        val store = SlowStore(StoredTokens("acc-expired", "ref-0"))
        val repo = repo(store)
        withContext(Dispatchers.IO) {
            val session = async { repo.currentSession() }
            delay(150) // refresh is now in flight (server holds it ~300 ms)
            val logout = launch { repo.logout() }
            session.await()
            logout.join()
        }
        assertNull(store.read())
        assertEquals(1, model.logoutBodies.size)
        // Logout ran after the refresh finished, so it revoked with the NEW refresh token.
        assertTrue(model.logoutBodies[0], model.logoutBodies[0].contains("\"refresh_token\":\"ref-1\""))
        // A later check stays signed out (no stale credentials resurrected).
        assertEquals(SessionState.SignedOut, repo.currentSession())
    }
}
