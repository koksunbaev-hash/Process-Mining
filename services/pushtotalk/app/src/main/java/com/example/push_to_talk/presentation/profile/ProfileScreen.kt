package com.example.push_to_talk.presentation.profile

import android.content.res.Configuration
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.example.push_to_talk.AppLanguage
import com.example.push_to_talk.R
import java.util.Locale

@Composable
fun ProfileScreen(
    username: String,
    isDarkTheme: Boolean,
    appLanguage: AppLanguage,
    onDarkThemeChange: (Boolean) -> Unit,
    onLanguageChange: (AppLanguage) -> Unit,
    onLogout: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LocalizedProfileContent(appLanguage = appLanguage) {
        Column(
            modifier = modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = stringResource(R.string.profile_title),
                style = MaterialTheme.typography.headlineSmall,
            )

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = stringResource(R.string.profile_username_label),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = username.ifBlank { stringResource(R.string.profile_username_unknown) },
                        style = MaterialTheme.typography.titleMedium,
                    )
                }
            }

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = stringResource(R.string.settings_theme),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Switch(
                            checked = isDarkTheme,
                            onCheckedChange = onDarkThemeChange,
                        )
                    }

                    Text(
                        text = stringResource(R.string.settings_language),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        AppLanguage.values().forEach { language ->
                            FilterChip(
                                selected = appLanguage == language,
                                onClick = { onLanguageChange(language) },
                                label = {
                                    Text(
                                        text = stringResource(
                                            when (language) {
                                                AppLanguage.Kk -> R.string.language_kz
                                                AppLanguage.Ru -> R.string.language_ru
                                            },
                                        ),
                                    )
                                },
                            )
                        }
                    }
                }
            }

            Button(
                onClick = onLogout,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(text = stringResource(R.string.profile_logout))
            }
        }
    }
}

@Composable
private fun LocalizedProfileContent(
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
