package com.example.push_to_talk.presentation.navigation

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.material3.Icon
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.example.push_to_talk.AppLanguage
import com.example.push_to_talk.R
import com.example.push_to_talk.presentation.main.MainRoute
import com.example.push_to_talk.presentation.profile.ProfileScreen

@Composable
fun PushToTalkNavHost(
    username: String,
    isDarkTheme: Boolean,
    appLanguage: AppLanguage,
    onDarkThemeChange: (Boolean) -> Unit,
    onLanguageChange: (AppLanguage) -> Unit,
    onLogout: () -> Unit,
    modifier: Modifier = Modifier,
    navController: NavHostController = rememberNavController(),
) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route ?: HOME_ROUTE

    Scaffold(
        modifier = modifier.fillMaxSize(),
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = currentRoute == HOME_ROUTE,
                    onClick = { navController.openSingleTop(HOME_ROUTE) },
                    label = { Text(text = stringResource(R.string.nav_home)) },
                    icon = {
                        Icon(
                            painter = painterResource(R.drawable.ic_nav_home),
                            contentDescription = null,
                        )
                    },
                )
                NavigationBarItem(
                    selected = currentRoute == PROFILE_ROUTE,
                    onClick = { navController.openSingleTop(PROFILE_ROUTE) },
                    label = { Text(text = stringResource(R.string.nav_profile)) },
                    icon = {
                        Icon(
                            painter = painterResource(R.drawable.ic_nav_profile),
                            contentDescription = null,
                        )
                    },
                )
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = HOME_ROUTE,
            modifier = Modifier.padding(innerPadding),
        ) {
            composable(HOME_ROUTE) {
                MainRoute(appLanguage = appLanguage)
            }
            composable(PROFILE_ROUTE) {
                ProfileScreen(
                    username = username,
                    isDarkTheme = isDarkTheme,
                    appLanguage = appLanguage,
                    onDarkThemeChange = onDarkThemeChange,
                    onLanguageChange = onLanguageChange,
                    onLogout = onLogout,
                )
            }
        }
    }
}

private fun NavHostController.openSingleTop(route: String) {
    navigate(route) {
        launchSingleTop = true
        restoreState = true
        popUpTo(HOME_ROUTE) {
            saveState = true
        }
    }
}

private const val HOME_ROUTE = "home"
private const val PROFILE_ROUTE = "profile"
