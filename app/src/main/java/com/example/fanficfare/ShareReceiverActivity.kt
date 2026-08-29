package com.example.fanficfare

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.core.view.WindowCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class ShareReceiverActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        val text = TextView(this)
        text.visibility = View.GONE
        setContentView(text)

        handleSharedUrl(intent)
        scope.launch { delay(500) }
        finish()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleSharedUrl(intent)
        scope.launch { delay(500) }
        finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    private fun handleSharedUrl(intent: Intent) {
        if (intent.action != Intent.ACTION_SEND || intent.type != "text/plain") return
        val url = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim().orEmpty()
        if (url.isBlank() || !url.startsWith("http")) return
        DiagnosticLog.append(this, "Main.Shared", "shared_url=$url")
        val toast = android.widget.Toast.makeText(this, "Sharing download: ${android.net.Uri.parse(url).host ?: url}", android.widget.Toast.LENGTH_SHORT)
        toast.show()
        scope.launch {
            BookRepository(this@ShareReceiverActivity).enqueueDownload(url)
        }
        DiagnosticLog.append(this, "Main.Shared", "enqueued_download url=$url")
    }
}
