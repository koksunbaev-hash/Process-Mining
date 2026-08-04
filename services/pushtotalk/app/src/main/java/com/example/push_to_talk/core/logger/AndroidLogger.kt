package com.example.push_to_talk.core.logger

import android.util.Log
import com.example.push_to_talk.BuildConfig
import javax.inject.Inject
import javax.inject.Singleton

/** Реализация [Logger] поверх [Log]. Debug-уровень пишется только в debug-сборках. */
@Singleton
class AndroidLogger @Inject constructor() : Logger {

    override fun d(tag: String, message: String) {
        if (BuildConfig.DEBUG) {
            Log.d(prefixed(tag), message)
        }
    }

    override fun i(tag: String, message: String) {
        Log.i(prefixed(tag), message)
    }

    override fun w(tag: String, message: String, throwable: Throwable?) {
        Log.w(prefixed(tag), message, throwable)
    }

    override fun e(tag: String, message: String, throwable: Throwable?) {
        Log.e(prefixed(tag), message, throwable)
    }

    private fun prefixed(tag: String): String = "$TAG_PREFIX$tag".take(MAX_TAG_LENGTH)

    private companion object {
        const val TAG_PREFIX = "PTT/"

        /** Ограничение платформы на длину тега до Android 8.0. */
        const val MAX_TAG_LENGTH = 23
    }
}
