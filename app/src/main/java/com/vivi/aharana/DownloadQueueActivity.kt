package com.vivi.aharana

import android.os.Bundle
import android.widget.LinearLayout
import androidx.recyclerview.widget.LinearLayoutManager
import com.vivi.aharana.adapter.DownloadJobAdapter
import com.vivi.aharana.data.local.AppDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class DownloadQueueActivity : BaseActivity() {

    private lateinit var adapter: DownloadJobAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_download_queue)
        applyTopInset(findViewById<android.view.View>(R.id.appBar))
        applyBottomInset(findViewById<android.view.View>(R.id.contentContainer))

        setSupportActionBar(findViewById(R.id.toolbar))
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.setHomeActionContentDescription("Back")

        val recycler = findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.recyclerJobs)
        val emptyState = findViewById<LinearLayout>(R.id.emptyState)

        adapter = DownloadJobAdapter(
            onRetry = { job ->
                DiagnosticLog.append(this, "Queue.Retry", "jobId=${job.id} type=${job.type}")
                val repo = BookRepository(this)
                repo.retryJob(job)
                showMessage(R.string.retry_failed_toast)
                // Mark the old job as cancelled so it disappears from the queue
                // and the retried job appears as a new entry
                repo.cancelJob(job)
            },
            onRemove = { job ->
                DiagnosticLog.append(this, "Queue.Remove", "jobId=${job.id}")
                val db = AppDatabase.getInstance(this)
                CoroutineScope(Dispatchers.IO).launch {
                    db.downloadJobDao().delete(job)
                }
                showMessage(R.string.queue_removed_toast)
            }
        )

        recycler.layoutManager = LinearLayoutManager(this)
        recycler.adapter = adapter

        val db = AppDatabase.getInstance(this)
        db.downloadJobDao().observeAll().observe(this) { allJobs ->
            // Show download/update/force_download jobs that are not yet successful.
            // Metadata-fetch jobs (type == "metadata") are internal background lookups
            // and should NOT appear in the download queue — they are tracked
            // separately in AddFromPageActivity via observer callbacks.
            val visible = allJobs
                .filter { it.type != "metadata" && it.status != "success" && it.status != "cancelled" }
                .sortedByDescending { it.createdAt }
            adapter.submitList(visible.toList())
            if (visible.isEmpty()) {
                emptyState.visibility = LinearLayout.VISIBLE
                recycler.visibility = LinearLayout.GONE
            } else {
                emptyState.visibility = LinearLayout.GONE
                recycler.visibility = LinearLayout.VISIBLE
            }
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }
}
