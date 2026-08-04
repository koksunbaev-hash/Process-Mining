package com.example.push_to_talk.presentation.main

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.push_to_talk.R
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionStatus
import com.example.push_to_talk.presentation.main.components.MicButton
import com.example.push_to_talk.ui.theme.PushtotalkTheme

/**
 * Режим кнопки. Чтобы получить «удерживай для разговора», достаточно поменять значение:
 * ViewModel и весь слой ниже остаются без изменений.
 */
private val PushToTalkButtonMode = PushToTalkMode.Tap

/** Точка входа экрана: связывает ViewModel, разрешения и stateless-UI. */
@Composable
fun MainRoute(
    modifier: Modifier = Modifier,
    viewModel: MainViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
        onResult = viewModel::onPermissionResult,
    )

    LifecycleEventEffect(Lifecycle.Event.ON_START) {
        viewModel.refreshPermission()
    }

    var permissionRequested by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(uiState.hasMicrophonePermission) {
        if (!uiState.hasMicrophonePermission && !permissionRequested) {
            permissionRequested = true
            permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    if (uiState.hasMicrophonePermission) {
        MainScreen(
            uiState = uiState,
            mode = PushToTalkButtonMode,
            onMicTap = viewModel::onMicTap,
            onMicPressStart = viewModel::onMicPressStart,
            onMicPressEnd = viewModel::onMicPressEnd,
            onErrorDismissed = viewModel::onErrorDismissed,
            modifier = modifier,
        )
    } else {
        MicrophonePermissionScreen(
            onRequestPermission = { permissionLauncher.launch(Manifest.permission.RECORD_AUDIO) },
            onOpenSettings = {
                val intent = Intent(
                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.fromParts("package", context.packageName, null),
                ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
            },
            modifier = modifier,
        )
    }
}

@Composable
fun MainScreen(
    uiState: MainUiState,
    mode: PushToTalkMode,
    onMicTap: () -> Unit,
    onMicPressStart: () -> Unit,
    onMicPressEnd: () -> Unit,
    onErrorDismissed: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Scaffold(modifier = modifier.fillMaxSize()) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Top,
        ) {
            Text(
                text = stringResource(R.string.app_name),
                style = MaterialTheme.typography.headlineSmall,
            )

            Spacer(modifier = Modifier.height(32.dp))

            MicButton(
                isListening = uiState.isListening,
                isEnabled = !uiState.isSending,
                audioLevel = uiState.audioLevel,
                mode = mode,
                onTap = onMicTap,
                onPressStart = onMicPressStart,
                onPressEnd = onMicPressEnd,
            )

            Text(
                text = stringResource(
                    if (mode == PushToTalkMode.Tap) R.string.hint_tap else R.string.hint_hold,
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 12.dp),
            )

            Spacer(modifier = Modifier.height(24.dp))

            StatusSection(status = uiState.status)

            Spacer(modifier = Modifier.height(24.dp))

            RecognizedTextSection(text = uiState.recognizedText)

            SendStatusSection(sendStatus = uiState.sendStatus)

            uiState.error?.let { error ->
                Spacer(modifier = Modifier.height(16.dp))
                ErrorSection(error = error, onDismiss = onErrorDismissed)
            }
        }
    }
}

@Composable
private fun StatusSection(status: RecognitionStatus, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = stringResource(R.string.status_label),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = stringResource(status.labelRes()),
            style = MaterialTheme.typography.titleMedium,
        )
    }
}

/**
 * Итог отправки текста на сервер: «✅ Отправлено» либо «❌ Ошибка отправки».
 * Пока запрос в пути показывается прогресс-индикатор.
 */
@Composable
private fun SendStatusSection(sendStatus: SendStatus, modifier: Modifier = Modifier) {
    val messageRes = sendStatus.messageRes() ?: return

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(top = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = stringResource(messageRes),
            style = MaterialTheme.typography.bodyMedium,
            color = when (sendStatus) {
                SendStatus.Success -> MaterialTheme.colorScheme.primary
                SendStatus.Error -> MaterialTheme.colorScheme.error
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
        if (sendStatus == SendStatus.Sending) {
            LinearProgressIndicator(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp),
            )
        }
    }
}

@Composable
private fun RecognizedTextSection(text: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = stringResource(R.string.recognized_text_label),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = text.ifBlank { stringResource(R.string.recognized_text_placeholder) },
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
    }
}

@Composable
private fun ErrorSection(
    error: AppError,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
            contentColor = MaterialTheme.colorScheme.onErrorContainer,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = stringResource(error.messageRes()),
                style = MaterialTheme.typography.bodyMedium,
            )
            TextButton(
                onClick = onDismiss,
                modifier = Modifier.align(Alignment.End),
            ) {
                Text(text = stringResource(R.string.error_dismiss))
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun MainScreenIdlePreview() {
    PushtotalkTheme {
        MainScreen(
            uiState = MainUiState(hasMicrophonePermission = true),
            mode = PushToTalkMode.Tap,
            onMicTap = {},
            onMicPressStart = {},
            onMicPressEnd = {},
            onErrorDismissed = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun MainScreenListeningPreview() {
    PushtotalkTheme {
        MainScreen(
            uiState = MainUiState(
                status = RecognitionStatus.SpeechDetected,
                recognizedText = "Привет, это тестовая реплика",
                isListening = true,
                isSessionActive = true,
                hasMicrophonePermission = true,
                audioLevel = 0.6f,
            ),
            mode = PushToTalkMode.Tap,
            onMicTap = {},
            onMicPressStart = {},
            onMicPressEnd = {},
            onErrorDismissed = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun MainScreenSentPreview() {
    PushtotalkTheme {
        MainScreen(
            uiState = MainUiState(
                status = RecognitionStatus.Success,
                recognizedText = "Привет, сервер",
                hasMicrophonePermission = true,
                sendStatus = SendStatus.Success,
            ),
            mode = PushToTalkMode.Tap,
            onMicTap = {},
            onMicPressStart = {},
            onMicPressEnd = {},
            onErrorDismissed = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun MainScreenSendErrorPreview() {
    PushtotalkTheme {
        MainScreen(
            uiState = MainUiState(
                status = RecognitionStatus.Success,
                recognizedText = "Привет, сервер",
                hasMicrophonePermission = true,
                sendStatus = SendStatus.Error,
                error = AppError.Network.NoConnection,
            ),
            mode = PushToTalkMode.Tap,
            onMicTap = {},
            onMicPressStart = {},
            onMicPressEnd = {},
            onErrorDismissed = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun MainScreenErrorPreview() {
    PushtotalkTheme {
        MainScreen(
            uiState = MainUiState(
                status = RecognitionStatus.Error,
                hasMicrophonePermission = true,
                error = AppError.Speech.NoSpeechDetected,
            ),
            mode = PushToTalkMode.Tap,
            onMicTap = {},
            onMicPressStart = {},
            onMicPressEnd = {},
            onErrorDismissed = {},
        )
    }
}
