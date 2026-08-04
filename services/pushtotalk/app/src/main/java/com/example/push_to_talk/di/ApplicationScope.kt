package com.example.push_to_talk.di

import javax.inject.Qualifier

/** [kotlinx.coroutines.CoroutineScope], живущий столько же, сколько процесс приложения. */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class ApplicationScope
