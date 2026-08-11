package com.example.push_to_talk.presentation.main.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.push_to_talk.R
import com.example.push_to_talk.presentation.main.PushToTalkMode
import com.example.push_to_talk.ui.theme.PushtotalkTheme

private val ButtonSize = 176.dp
private val MaxRingSize = 232.dp
private val MicIconSize = 64.sp

/**
 * РљСЂСѓРіР»Р°СЏ РєРЅРѕРїРєР° Push-to-Talk. Р РµР¶РёРј [PushToTalkMode] РІР»РёСЏРµС‚ С‚РѕР»СЊРєРѕ РЅР° СЃРїРѕСЃРѕР± РІРІРѕРґР°:
 * ViewModel РїРѕР»СѓС‡Р°РµС‚ С‚Рµ Р¶Рµ СЃР°РјС‹Рµ СЃРѕР±С‹С‚РёСЏ, РїРѕСЌС‚РѕРјСѓ Р±РёР·РЅРµСЃ-Р»РѕРіРёРєР° РЅРµ РјРµРЅСЏРµС‚СЃСЏ.
 */
@Composable
fun MicButton(
    isListening: Boolean,
    isEnabled: Boolean,
    audioLevel: Float,
    mode: PushToTalkMode,
    onTap: () -> Unit,
    onPressStart: () -> Unit,
    onPressEnd: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val ringSize by animateDpAsState(
        targetValue = if (isListening) {
            ButtonSize + (MaxRingSize - ButtonSize) * audioLevel.coerceIn(0f, 1f)
        } else {
            ButtonSize
        },
        label = "micRing",
    )
    val containerColor by animateColorAsState(
        targetValue = if (isListening) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.primaryContainer
        },
        label = "micContainer",
    )
    val contentColor = if (isListening) {
        MaterialTheme.colorScheme.onPrimary
    } else {
        MaterialTheme.colorScheme.onPrimaryContainer
    }

    val description = stringResource(
        if (isListening) R.string.mic_button_stop else R.string.mic_button_start,
    )

    val gestureModifier = when (mode) {
        PushToTalkMode.Tap -> Modifier.clickable(enabled = isEnabled, onClick = onTap)
        PushToTalkMode.Hold -> Modifier.pointerInput(isEnabled) {
            if (!isEnabled) return@pointerInput
            detectTapGestures(
                onPress = {
                    onPressStart()
                    tryAwaitRelease()
                    onPressEnd()
                },
            )
        }
    }

    Box(
        modifier = modifier.size(MaxRingSize),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(ringSize)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)),
        )
        Box(
            modifier = Modifier
                .size(ButtonSize)
                .clip(CircleShape)
                .background(containerColor)
                .then(gestureModifier)
                .semantics {
                    this.contentDescription = description
                    role = Role.Button
                },
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "\uD83C\uDFA4",
                fontSize = MicIconSize,
                color = contentColor,
            )
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun MicButtonIdlePreview() {
    PushtotalkTheme {
        MicButton(
            isListening = false,
            isEnabled = true,
            audioLevel = 0f,
            mode = PushToTalkMode.Tap,
            onTap = {},
            onPressStart = {},
            onPressEnd = {},
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun MicButtonListeningPreview() {
    PushtotalkTheme {
        MicButton(
            isListening = true,
            isEnabled = true,
            audioLevel = 0.7f,
            mode = PushToTalkMode.Tap,
            onTap = {},
            onPressStart = {},
            onPressEnd = {},
        )
    }
}

