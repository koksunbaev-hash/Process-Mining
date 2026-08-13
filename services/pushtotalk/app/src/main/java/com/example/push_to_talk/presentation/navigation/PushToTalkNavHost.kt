package com.example.push_to_talk.presentation.navigation

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.example.push_to_talk.AppLanguage
import com.example.push_to_talk.R
import com.example.push_to_talk.presentation.kanban.KanbanScreen
import com.example.push_to_talk.presentation.main.MainRoute
import com.example.push_to_talk.presentation.profile.ProfileScreen

@Composable
fun PushToTalkNavHost(
    username: String,
    kmsBaseUrl: String,
    kmsCookies: String,
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
                    icon = {
                        Icon(
                            painter = painterResource(R.drawable.ic_nav_home),
                            contentDescription = null,
                        )
                    },
                    label = { Text(text = stringResource(R.string.nav_home)) },
                )
                NavigationBarItem(
                    selected = currentRoute == KANBAN_ROUTE,
                    onClick = { navController.openSingleTop(KANBAN_ROUTE) },
                    icon = {
                        Icon(
                            painter = painterResource(R.drawable.ic_nav_kanban),
                            contentDescription = null,
                        )
                    },
                    label = { Text(text = stringResource(R.string.nav_kanban)) },
                )
                NavigationBarItem(
                    selected = currentRoute == PROFILE_ROUTE,
                    onClick = { navController.openSingleTop(PROFILE_ROUTE) },
                    icon = {
                        Icon(
                            painter = painterResource(R.drawable.ic_nav_profile),
                            contentDescription = null,
                        )
                    },
                    label = { Text(text = stringResource(R.string.nav_profile)) },
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
            composable(KANBAN_ROUTE) {
                KanbanScreen(
                    kmsBaseUrl = kmsBaseUrl,
                    kmsCookies = kmsCookies,
                )
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
private const val KANBAN_ROUTE = "kanban"
private const val PROFILE_ROUTE = "profile"