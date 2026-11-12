package app.densa.mediavault.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Navy = Color(0xFF0B1F3A)
val BrandBlue = Color(0xFF3B82F6)
private val BlueDeep = Color(0xFF2563EB)

private val LightColors = lightColorScheme(
    primary = BlueDeep,
    onPrimary = Color.White,
    secondary = Navy,
    onSecondary = Color.White,
    background = Color(0xFFF8FAFC),
    surface = Color.White,
    onSurface = Color(0xFF0F172A),
)

private val DarkColors = darkColorScheme(
    primary = BrandBlue,
    onPrimary = Color.White,
    secondary = Color(0xFF93C5FD),
    background = Color(0xFF020617),
    surface = Color(0xFF0F172A),
    onSurface = Color(0xFFE2E8F0),
)

@Composable
fun MediaVaultTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (darkTheme) DarkColors else LightColors, content = content)
}
