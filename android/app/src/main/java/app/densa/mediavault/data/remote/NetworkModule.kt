package app.densa.mediavault.data.remote

import app.densa.mediavault.data.auth.AuthApi
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

object NetworkModule {
    val json: Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    fun okHttpClient(): OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .callTimeout(15, TimeUnit.SECONDS)
            .build()

    fun retrofit(baseUrl: String, client: OkHttpClient = okHttpClient()): Retrofit =
        Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()

    fun createApi(baseUrl: String, client: OkHttpClient = okHttpClient()): HealthApi =
        retrofit(baseUrl, client).create(HealthApi::class.java)

    fun createAuthApi(baseUrl: String, client: OkHttpClient = okHttpClient()): AuthApi =
        retrofit(baseUrl, client).create(AuthApi::class.java)
}
