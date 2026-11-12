package app.densa.mediavault.data.remote

import kotlinx.serialization.Serializable
import retrofit2.Response
import retrofit2.http.GET

@Serializable
data class HealthChecksDto(val database: String)

@Serializable
data class HealthDto(
    val status: String,
    val service: String,
    val version: String,
    val environment: String,
    val checks: HealthChecksDto,
    val time: String,
)

interface HealthApi {
    /** Returns 200 when healthy and 503 (same body shape) when a dependency is down. */
    @GET("api/v1/health")
    suspend fun health(): Response<HealthDto>
}
