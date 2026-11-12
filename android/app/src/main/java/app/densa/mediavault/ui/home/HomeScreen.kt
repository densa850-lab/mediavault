package app.densa.mediavault.ui.home

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.densa.mediavault.R
import app.densa.mediavault.data.remote.HealthChecksDto
import app.densa.mediavault.data.remote.HealthDto
import app.densa.mediavault.ui.theme.BrandBlue
import app.densa.mediavault.ui.theme.MediaVaultTheme
import app.densa.mediavault.ui.theme.Navy

@Composable
fun HomeRoute(viewModel: HomeViewModel, serverUrl: String) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    HomeScreen(state = state, serverUrl = serverUrl, onRetry = viewModel::refresh)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(state: HomeUiState, serverUrl: String, onRetry: () -> Unit) {
    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        LogoMark(Modifier.size(28.dp))
                        Spacer(Modifier.size(8.dp))
                        Text(stringResource(R.string.app_name), fontWeight = FontWeight.SemiBold)
                    }
                },
                colors = TopAppBarDefaults.centerAlignedTopAppBarColors(
                    containerColor = Navy,
                    titleContentColor = Color.White,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                stringResource(R.string.home_title),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(stringResource(R.string.home_body), style = MaterialTheme.typography.bodyLarge)
            StatusCard(state = state, serverUrl = serverUrl, onRetry = onRetry)
            Text(
                stringResource(R.string.footer_legal),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun StatusCard(state: HomeUiState, serverUrl: String, onRetry: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("status_card")
            .semantics { liveRegion = LiveRegionMode.Polite },
    ) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            val (title, dot) = when (state) {
                HomeUiState.Loading -> stringResource(R.string.status_loading) to Color(0xFFCBD5E1)
                is HomeUiState.Connected -> stringResource(R.string.status_connected) to Color(0xFF10B981)
                is HomeUiState.Degraded -> stringResource(R.string.status_degraded) to Color(0xFFF59E0B)
                is HomeUiState.Error -> stringResource(R.string.status_error) to Color(0xFFEF4444)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (state == HomeUiState.Loading) {
                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                } else {
                    Box(Modifier.size(12.dp).background(dot, CircleShape))
                }
                Spacer(Modifier.size(10.dp))
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            }
            when (state) {
                is HomeUiState.Connected -> HealthDetails(state.health)
                is HomeUiState.Degraded -> HealthDetails(state.health)
                is HomeUiState.Error -> Text(
                    stringResource(R.string.status_error_hint, serverUrl),
                    style = MaterialTheme.typography.bodyMedium,
                )
                HomeUiState.Loading -> Unit
            }
            if (state != HomeUiState.Loading) {
                Button(onClick = onRetry) { Text(stringResource(R.string.action_retry)) }
            }
        }
    }
}

@Composable
private fun HealthDetails(health: HealthDto) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        DetailRow(stringResource(R.string.label_service), health.service)
        DetailRow(stringResource(R.string.label_version), health.version)
        DetailRow(stringResource(R.string.label_environment), health.environment)
        DetailRow(
            stringResource(R.string.label_database),
            stringResource(if (health.checks.database == "ok") R.string.db_ok else R.string.db_error),
        )
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth()) {
        Text(label, Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, Modifier.weight(1f))
    }
}

/** Original MediaVault mark drawn in code: vault ring + play triangle. */
@Composable
private fun LogoMark(modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val r = size.minDimension / 2
        drawCircle(color = BrandBlue, radius = r * 0.8f, style = Stroke(width = r * 0.18f))
        val path = Path().apply {
            moveTo(size.width * 0.42f, size.height * 0.32f)
            lineTo(size.width * 0.70f, size.height * 0.50f)
            lineTo(size.width * 0.42f, size.height * 0.68f)
            close()
        }
        drawPath(path, Color.White)
    }
}

private val previewHealth = HealthDto(
    status = "ok",
    service = "mediavault-api",
    version = "0.1.0",
    environment = "development",
    checks = HealthChecksDto(database = "ok"),
    time = "2026-11-12T16:00:00Z",
)

@Preview(showBackground = true)
@Composable
private fun HomeConnectedPreview() {
    MediaVaultTheme { HomeScreen(HomeUiState.Connected(previewHealth), "http://10.0.2.2:8000/") {} }
}

@Preview(showBackground = true)
@Composable
private fun HomeErrorPreview() {
    MediaVaultTheme { HomeScreen(HomeUiState.Error("Failed to connect"), "http://10.0.2.2:8000/") {} }
}
