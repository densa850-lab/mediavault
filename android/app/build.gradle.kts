import java.net.URI
import java.net.URISyntaxException

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

val debugApiBaseUrl = providers.gradleProperty("mediavault.apiBaseUrl").getOrElse("http://10.0.2.2:8000/")

// Release builds must point at a real HTTPS server: pass -Pmediavault.releaseApiBaseUrl=https://...
// There is deliberately NO fallback (MV-003). Any task that builds the release variant
// (assembleRelease, bundleRelease, lintVitalRelease, ...) fails in validateReleaseApiBaseUrl when
// the property is missing, malformed or not https. Debug builds are unaffected.
val releaseApiBaseUrlProperty = providers.gradleProperty("mediavault.releaseApiBaseUrl")

/** Returns null when [raw] is an acceptable release API base URL, otherwise the reason. */
fun releaseApiBaseUrlProblem(raw: String?): String? {
    if (raw.isNullOrBlank()) return "the Gradle property mediavault.releaseApiBaseUrl is not set"
    if (raw.any { it.isWhitespace() || it == '"' || it == '\\' || it == '$' }) {
        return "it contains whitespace, quotes, backslashes or '$'"
    }
    val uri = try {
        URI(raw)
    } catch (_: URISyntaxException) {
        return "it is not a valid URL"
    }
    val host = uri.host?.lowercase()
    return when {
        !uri.isAbsolute || uri.scheme?.lowercase() != "https" -> "it must start with https://"
        host.isNullOrEmpty() -> "it has no host name"
        uri.rawUserInfo != null -> "it must not contain user credentials"
        uri.rawQuery != null || uri.rawFragment != null -> "it must not contain a query or fragment"
        !uri.rawPath.orEmpty().endsWith("/") -> "it must end with '/' (Retrofit base URL)"
        host == "localhost" || host.endsWith(".invalid") -> "'$host' is a placeholder, not a real server"
        else -> null
    }
}

val releaseApiBaseUrl: String = releaseApiBaseUrlProperty.orNull?.takeIf { releaseApiBaseUrlProblem(it) == null } ?: ""

val validateReleaseApiBaseUrl = tasks.register("validateReleaseApiBaseUrl") {
    group = "verification"
    description = "Fails unless -Pmediavault.releaseApiBaseUrl is a real https:// URL."
    val value = releaseApiBaseUrlProperty.orElse("")
    inputs.property("releaseApiBaseUrl", value)
    doLast {
        releaseApiBaseUrlProblem(value.get().ifEmpty { null })?.let { problem ->
            throw GradleException(
                "Release build refused: $problem. Pass the production API URL, e.g. " +
                    "./gradlew assembleRelease -Pmediavault.releaseApiBaseUrl=https://api.your-domain.com/",
            )
        }
    }
}

// Every release-variant task graph starts at preReleaseBuild.
tasks.matching { it.name == "preReleaseBuild" }.configureEach { dependsOn(validateReleaseApiBaseUrl) }

android {
    namespace = "app.densa.mediavault"
    // Compose BOM 2026.09, core-ktx 1.19 and OkHttp 5.5 require compiling against API 37.
    // targetSdk stays 36 (the Play requirement); bump it deliberately after testing Android 17 behavior.
    compileSdk = 37

    defaultConfig {
        applicationId = "app.densa.mediavault"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        debug {
            buildConfigField("String", "API_BASE_URL", "\"$debugApiBaseUrl\"")
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            buildConfigField("String", "API_BASE_URL", "\"$releaseApiBaseUrl\"")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
        unitTests.all { test ->
            System.getenv("MEDIAVAULT_LIVE_API_URL")?.let { test.environment("MEDIAVAULT_LIVE_API_URL", it) }
        }
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization)
    implementation(libs.okhttp)
    debugImplementation(libs.compose.ui.tooling)
    debugImplementation(libs.compose.ui.test.manifest)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)

    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.junit)
}
