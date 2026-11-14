package app.densa.mediavault.ui.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.densa.mediavault.R
import app.densa.mediavault.data.auth.MIN_PASSWORD_LENGTH
import app.densa.mediavault.ui.theme.Navy

@Composable
fun AuthRoute(viewModel: AuthViewModel, onBack: () -> Unit) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    AuthScreen(
        state = state,
        onBack = onBack,
        onSubmit = viewModel::submit,
        onModeChange = viewModel::setMode,
        onLogout = viewModel::logout,
        onRetry = viewModel::loadSession,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AuthScreen(
    state: AuthUiState,
    onBack: () -> Unit,
    onSubmit: (email: String, password: String) -> Unit,
    onModeChange: (AuthMode) -> Unit,
    onLogout: () -> Unit,
    onRetry: () -> Unit = {},
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.account_title)) },
                navigationIcon = {
                    TextButton(onClick = onBack) {
                        Text(stringResource(R.string.action_back), color = Color.White)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Navy,
                    titleContentColor = Color.White,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            when (state) {
                AuthUiState.Checking -> CircularProgressIndicator(Modifier.testTag("auth_checking"))
                is AuthUiState.SignedIn -> {
                    Text(stringResource(R.string.signed_in_as, state.email), style = MaterialTheme.typography.titleMedium)
                    OutlinedButton(onClick = onLogout) { Text(stringResource(R.string.action_sign_out)) }
                }
                is AuthUiState.SignedOut -> AuthForm(state, onSubmit, onModeChange)
                is AuthUiState.Unavailable -> {
                    Text(state.message, color = MaterialTheme.colorScheme.error, modifier = Modifier.testTag("auth_unavailable"))
                    Button(onClick = onRetry, modifier = Modifier.testTag("auth_retry")) {
                        Text(stringResource(R.string.action_retry_session))
                    }
                }
            }
        }
    }
}

@Composable
private fun AuthForm(
    state: AuthUiState.SignedOut,
    onSubmit: (String, String) -> Unit,
    onModeChange: (AuthMode) -> Unit,
) {
    var email by rememberSaveable { mutableStateOf("") }
    // Not saveable: the password is never written to saved instance state.
    var password by remember { mutableStateOf("") }
    var localError by remember { mutableStateOf<String?>(null) }
    val isLogin = state.mode == AuthMode.Login
    val tooShort = pluralStringResource(R.plurals.password_too_short, MIN_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH)

    Text(
        stringResource(if (isLogin) R.string.sign_in_title else R.string.register_title),
        style = MaterialTheme.typography.headlineSmall,
    )
    OutlinedTextField(
        value = email,
        onValueChange = { email = it },
        label = { Text(stringResource(R.string.label_email)) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
        modifier = Modifier.fillMaxWidth().testTag("email_field"),
    )
    OutlinedTextField(
        value = password,
        onValueChange = { password = it },
        label = { Text(stringResource(R.string.label_password)) },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        modifier = Modifier.fillMaxWidth().testTag("password_field"),
    )
    if (!isLogin) {
        Text(pluralStringResource(R.plurals.password_hint, MIN_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH), style = MaterialTheme.typography.bodySmall)
    }
    val error = localError ?: state.error
    if (error != null) {
        Text(error, color = MaterialTheme.colorScheme.error, modifier = Modifier.testTag("auth_error"))
    }
    state.notice?.let { Text(it, modifier = Modifier.testTag("auth_notice")) }
    Button(
        enabled = !state.busy,
        onClick = {
            localError = null
            if (!isLogin && password.length < MIN_PASSWORD_LENGTH) {
                localError = tooShort
            } else {
                onSubmit(email, password)
            }
        },
        modifier = Modifier.fillMaxWidth().testTag("auth_submit"),
    ) {
        Text(stringResource(if (isLogin) R.string.action_sign_in else R.string.action_create_account))
    }
    TextButton(onClick = {
        localError = null
        onModeChange(if (isLogin) AuthMode.Register else AuthMode.Login)
    }) {
        Text(stringResource(if (isLogin) R.string.switch_to_register else R.string.switch_to_login))
    }
}
