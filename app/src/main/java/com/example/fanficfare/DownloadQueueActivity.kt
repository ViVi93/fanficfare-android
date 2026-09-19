package com.example.fanficfare

import android.os.Bundle
import android.widget.LinearLayout
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.fanficfare.adapter.DownloadJobAdapter
import com.example.fanficfare.data.local.AppDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class DownloadQueueActivity : AppCompatActivity() {

    private lateinit var adapter: DownloadJobAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            androidx.core.view.WindowCompat.setDecorFitsSystemWindows(window, true)
        }
        setContentView(R.layout.activity_download_queue)

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
                Toast.makeText(this, R.string.retry_failed_toast, Toast.LENGTH_LONG).show()
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
                Toast.makeText(this, R.string.queue_removed_toast, Toast.LENGTH_SHORT).show()
            }
        )

        recycler.layoutManager = LinearLayoutManager(this)
        recycler.adapter = adapter

        val db = AppDatabase.getInstance(this)
        db.downloadJobDao().observeAll().observe(this) { allJobs ->
            // Show all jobs EXCEPT successfully completed ones — they move to the library
            // Sort by most recent first
            val visible = allJobs
                .filter { it.status != "success" }
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
