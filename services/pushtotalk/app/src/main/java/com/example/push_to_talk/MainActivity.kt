package com.example.push_to_talk

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.example.push_to_talk.presentation.navigation.PushToTalkNavHost
import com.example.push_to_talk.ui.theme.PushtotalkTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            PushtotalkTheme {
                PushToTalkNavHost()
            }
        }
    }
}
