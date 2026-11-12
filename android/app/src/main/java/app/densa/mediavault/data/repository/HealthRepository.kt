package app.densa.mediavault.data.repository

import app.densa.mediavault.data.remote.HealthApi
import app.densa.mediavault.data.remote.HealthDto
import app.densa.mediavault.data.remote.NetworkModule
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.SerializationException

sealed interface HealthResult {
    data class Healthy(val health: HealthDto) : HealthResult
    data class Degraded(val health: HealthDto) : HealthResult
    data class Unreachable(val reason: String) : HealthResult
}

interface HealthRepository {
    suspend fun check(): HealthResult
}

class NetworkHealthRepository(private val api: HealthApi) : HealthRepository {
    override suspend fun check(): HealthResult =
        try {
            val res = api.health()
            when {
                res.isSuccessful && res.body() != null -> {
                    val body = res.body()!!
                    if (body.status == "ok") HealthResult.Healthy(body) else HealthResult.Degraded(body)
                }
                res.code() == 503 -> {
                    // Retrofit puts non-2xx bodies in errorBody(); the 503 body has the same shape.
                    val raw = res.errorBody()?.string()
                    val body = raw?.let { runCatching { NetworkModule.json.decodeFromString<HealthDto>(it) }.getOrNull() }
                    if (body != null) HealthResult.Degraded(body) else HealthResult.Unreachable("HTTP 503")
                }
                else -> HealthResult.Unreachable("HTTP ${res.code()}")
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            HealthResult.Unreachable(e.message ?: "Network error")
        } catch (e: SerializationException) {
            HealthResult.Unreachable("Unexpected response")
        }
}
