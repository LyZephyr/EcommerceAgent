package com.example.ecommerceragagent

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.example.ecommerceragagent.ui.chat.ChatRoute
import com.example.ecommerceragagent.ui.theme.EcommerceRagAgentTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            EcommerceRagAgentTheme {
                ChatRoute()
            }
        }
    }
}
