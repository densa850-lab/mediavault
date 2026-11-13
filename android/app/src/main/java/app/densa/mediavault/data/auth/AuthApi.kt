package app.densa.mediavault.data.auth

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST

@Serializable
data class CredentialsDto(val email: String, val password: String)

@Serializable
data class RefreshDto(@SerialName("refresh_token") val refreshToken: String)

@Serializable
data class LogoutDto(@SerialName("refresh_token") val refreshToken: String?)

@Serializable
data class TokenDto(
    @SerialName("access_token") val accessToken: String,
    @SerialName("expires_in") val expiresIn: Long,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("refresh_expires_in") val refreshExpiresIn: Long,
)

@Serializable
data class UserDto(val id: String, val email: String)

/** /api/v1/auth on the MediaVault API. */
interface AuthApi {
    @POST("api/v1/auth/register")
    suspend fun register(@Body body: CredentialsDto): Response<Unit>

    @POST("api/v1/auth/login")
    suspend fun login(@Body body: CredentialsDto): Response<TokenDto>

    @POST("api/v1/auth/refresh")
    suspend fun refresh(@Body body: RefreshDto): Response<TokenDto>

    @POST("api/v1/auth/logout")
    suspend fun logout(@Header("Authorization") bearer: String?, @Body body: LogoutDto): Response<Unit>

    @GET("api/v1/auth/me")
    suspend fun me(@Header("Authorization") bearer: String): Response<UserDto>
}
