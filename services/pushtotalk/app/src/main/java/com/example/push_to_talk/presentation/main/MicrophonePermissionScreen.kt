package com.example.push_to_talk.presentation.main

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.example.push_to_talk.R
import com.example.push_to_talk.ui.theme.PushtotalkTheme

/** Экран, который показывается, пока нет разрешения на запись аудио. */
@Composable
fun MicrophonePermissionScreen(
    onRequestPermission: () -> Unit,
    onOpenSettings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = stringResource(R.string.permission_title),
            style = MaterialTheme.typography.headlineSmall,
            textAlign = TextAlign.Center,
        )
        Text(
            text = stringResource(R.string.permission_message),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 12.dp),
        )
        Button(
            onClick = onRequestPermission,
            modifier = Modifier.padding(top = 24.dp),
        ) {
            Text(text = stringResource(R.string.permission_grant))
        }
        TextButton(onClick = onOpenSettings) {
            Text(text = stringResource(R.string.permission_open_settings))
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun MicrophonePermissionScreenPreview() {
    PushtotalkTheme {
        MicrophonePermissionScreen(onRequestPermission = {}, onOpenSettings = {})
    }
}
