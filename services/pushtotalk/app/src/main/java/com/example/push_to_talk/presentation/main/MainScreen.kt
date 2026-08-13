package com.example.push_to_talk.presentation.main

import android.Manifest
import android.content.res.Configuration
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.push_to_talk.AppLanguage
import com.example.push_to_talk.R
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionStatus
import com.example.push_to_talk.presentation.main.components.MicButton
import com.example.push_to_talk.ui.theme.PushtotalkTheme
import java.util.Locale

/**
 * Р РµР¶РёРј РєРЅРѕРїРєРё. Р§С‚РѕР±С‹ РїРѕР»СѓС‡РёС‚СЊ В«СѓРґРµСЂР¶РёРІР°Р№ РґР»СЏ СЂР°Р·РіРѕРІРѕСЂР°В», РґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РїРѕРјРµРЅСЏС‚СЊ Р·РЅР°С‡РµРЅРёРµ:
 * ViewModel Рё РІРµСЃСЊ СЃР»РѕР№ РЅРёР¶Рµ РѕСЃС‚Р°СЋС‚СЃСЏ Р±РµР· РёР·РјРµРЅРµРЅРёР№.
 */
private val PushToTalkButtonMode = PushToTalkMode.Tap
private const val SEND_DELAY_SECONDS = 3

/** РўРѕС‡РєР° РІС…РѕРґР° СЌРєСЂР°РЅР°: СЃРІСЏР·С‹РІР°РµС‚ ViewModel, СЂР°Р·СЂРµС€РµРЅРёСЏ Рё stateless-UI. */
@Composable
fun MainRoute(
    appLanguage: AppLanguage,
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

    LocalizedContent(appLanguage = appLanguage) {
        if (uiState.hasMicrophonePermission) {
            MainScreen(
                uiState = uiState,
                mode = PushToTalkButtonMode,
                onMicTap = viewModel::onMicTap,
                onMicPressStart = viewModel::onMicPressStart,
                onMicPressEnd = viewModel::onMicPressEnd,
                onErrorDismissed = viewModel::onErrorDismissed,
                onPendingSendCancelled = viewModel::onPendingSendCancelled,
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
    }}

@Composable
private fun LocalizedContent(
    appLanguage: AppLanguage,
    content: @Composable () -> Unit,
) {
    val baseContext = LocalContext.current
    val localizedConfiguration = remember(baseContext, appLanguage) {
        val locale = Locale.forLanguageTag(appLanguage.tag)
        Locale.setDefault(locale)
        Configuration(baseContext.resources.configuration).apply {
            setLocale(locale)
        }
    }
    val localizedContext = remember(baseContext, localizedConfiguration) {
        baseContext.createConfigurationContext(localizedConfiguration)
    }

    CompositionLocalProvider(
        LocalContext provides localizedContext,
        LocalConfiguration provides localizedConfiguration,
    ) {
        content()
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
    onPendingSendCancelled: () -> Unit,
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

            Spacer(modifier = Modifier.height(20.dp))

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

            SendStatusSection(
                sendStatus = uiState.sendStatus,
                sendDetail = uiState.sendDetail,
                pendingSendSeconds = uiState.pendingSendSeconds,
                onPendingSendCancelled = onPendingSendCancelled,
            )

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
 * РС‚РѕРі РѕС‚РїСЂР°РІРєРё С‚РµРєСЃС‚Р° РЅР° СЃРµСЂРІРµСЂ: В«вњ… РћС‚РїСЂР°РІР»РµРЅРѕВ» Р»РёР±Рѕ В«вќЊ РћС€РёР±РєР° РѕС‚РїСЂР°РІРєРёВ».
 * РџРѕРєР° Р·Р°РїСЂРѕСЃ РІ РїСѓС‚Рё РїРѕРєР°Р·С‹РІР°РµС‚СЃСЏ РїСЂРѕРіСЂРµСЃСЃ-РёРЅРґРёРєР°С‚РѕСЂ.
 */
@Composable
private fun SendStatusSection(
    sendStatus: SendStatus,
    sendDetail: String?,
    pendingSendSeconds: Int,
    onPendingSendCancelled: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val messageRes = sendStatus.messageRes() ?: return

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(top = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = if (sendStatus == SendStatus.Pending) {
                stringResource(messageRes, pendingSendSeconds)
            } else {
                stringResource(messageRes)
            },
            style = MaterialTheme.typography.bodyMedium,
            color = when (sendStatus) {
                SendStatus.Success -> MaterialTheme.colorScheme.primary
                SendStatus.CommandRejected -> MaterialTheme.colorScheme.error
                SendStatus.Error -> MaterialTheme.colorScheme.error
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
        if (!sendDetail.isNullOrBlank()) {
            Text(
                text = sendDetail,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        if (sendStatus == SendStatus.Pending) {
            PendingSendCountdown(secondsLeft = pendingSendSeconds)
            TextButton(onClick = onPendingSendCancelled) {
                Text(text = stringResource(R.string.send_status_cancel))
            }
        }
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
private fun PendingSendCountdown(secondsLeft: Int, modifier: Modifier = Modifier) {
    val safeSeconds = secondsLeft.coerceIn(0, SEND_DELAY_SECONDS)
    val progress = safeSeconds / SEND_DELAY_SECONDS.toFloat()

    Box(
        modifier = modifier
            .padding(top = 12.dp)
            .size(72.dp),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator(
            progress = { progress },
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.primary,
            trackColor = MaterialTheme.colorScheme.surfaceVariant,
            strokeWidth = 6.dp,
        )
        Text(
            text = safeSeconds.toString(),
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.primary,
        )
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
            onPendingSendCancelled = {},
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
                recognizedText = "РџСЂРёРІРµС‚, СЌС‚Рѕ С‚РµСЃС‚РѕРІР°СЏ СЂРµРїР»РёРєР°",
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
            onPendingSendCancelled = {},
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
                recognizedText = "РџСЂРёРІРµС‚, СЃРµСЂРІРµСЂ",
                hasMicrophonePermission = true,
                sendStatus = SendStatus.Success,
            ),
            mode = PushToTalkMode.Tap,
            onMicTap = {},
            onMicPressStart = {},
            onMicPressEnd = {},
            onErrorDismissed = {},
            onPendingSendCancelled = {},
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
                recognizedText = "РџСЂРёРІРµС‚, СЃРµСЂРІРµСЂ",
                hasMicrophonePermission = true,
                sendStatus = SendStatus.Error,
                error = AppError.Network.NoConnection,
            ),
            mode = PushToTalkMode.Tap,
            onMicTap = {},
            onMicPressStart = {},
            onMicPressEnd = {},
            onErrorDismissed = {},
            onPendingSendCancelled = {},
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
            onPendingSendCancelled = {},
        )
    }
}









