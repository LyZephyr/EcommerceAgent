package com.example.ecommerceragagent.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AddShoppingCart
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.example.ecommerceragagent.data.model.Cart
import com.example.ecommerceragagent.data.model.CartItem
import com.example.ecommerceragagent.data.model.CompareTable
import com.example.ecommerceragagent.data.model.Message
import com.example.ecommerceragagent.data.model.MessageRole
import com.example.ecommerceragagent.data.model.Product
import com.example.ecommerceragagent.viewmodel.ChatViewModel
import java.text.NumberFormat
import java.util.Locale

@Composable
fun ChatRoute(
    viewModel: ChatViewModel = viewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    ChatScreen(
        messages = uiState.messages,
        isLoading = uiState.isLoading,
        cart = uiState.cart,
        isCartLoading = uiState.isCartLoading,
        cartError = uiState.cartError,
        onSendMessage = viewModel::sendMessage,
        onCancelResponse = viewModel::cancelResponse,
        onAddToCart = viewModel::addToCart,
        onIncrementCartItem = viewModel::incrementCartItem,
        onDecrementCartItem = viewModel::decrementCartItem,
        onRemoveCartItem = viewModel::removeCartItem,
        onClearCart = viewModel::clearCart
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    messages: List<Message>,
    isLoading: Boolean,
    cart: Cart,
    isCartLoading: Boolean,
    cartError: String?,
    onSendMessage: (String) -> Unit,
    onCancelResponse: () -> Unit,
    onAddToCart: (Product) -> Unit,
    onIncrementCartItem: (String) -> Unit,
    onDecrementCartItem: (String) -> Unit,
    onRemoveCartItem: (String) -> Unit,
    onClearCart: () -> Unit
) {
    val listState = rememberLazyListState()
    var input by rememberSaveable { mutableStateOf("") }
    var selectedProduct by remember { mutableStateOf<Product?>(null) }
    var showCart by rememberSaveable { mutableStateOf(false) }

    LaunchedEffect(messages.size, messages.lastOrNull()?.content) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.lastIndex)
        }
    }

    selectedProduct?.let { product ->
        ProductDialog(
            product = product,
            onAddToCart = {
                onAddToCart(product)
                selectedProduct = null
            },
            onDismiss = { selectedProduct = null }
        )
    }

    if (showCart) {
        CartSheet(
            cart = cart,
            isCartLoading = isCartLoading,
            cartError = cartError,
            onDismiss = { showCart = false },
            onIncrement = onIncrementCartItem,
            onDecrement = onDecrementCartItem,
            onRemove = onRemoveCartItem,
            onClear = onClearCart
        )
    }

    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing),
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = "电商导购助手",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.SemiBold
                        )
                        Text(
                            text = if (isLoading) "正在检索商品并生成回复" else "RAG 商品推荐",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { showCart = true }) {
                        BadgedBox(
                            badge = {
                                if (cart.totalQuantity > 0) {
                                    Badge { Text(cart.totalQuantity.toString()) }
                                }
                            }
                        ) {
                            Icon(
                                imageVector = Icons.Default.ShoppingCart,
                                contentDescription = "购物车"
                            )
                        }
                    }
                }
            )
        },
        bottomBar = {
            Column {
                if (cart.totalQuantity > 0 || cartError != null || cart.messages.isNotEmpty()) {
                    CartSummaryBar(
                        cart = cart,
                        cartError = cartError,
                        isCartLoading = isCartLoading,
                        onClick = { showCart = true }
                    )
                }
                ChatInputBar(
                    input = input,
                    isLoading = isLoading,
                    onInputChange = { input = it },
                    onSend = {
                        onSendMessage(input)
                        input = ""
                    },
                    onCancel = onCancelResponse
                )
            }
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .padding(padding),
            state = listState,
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            items(messages, key = { it.id }) { message ->
                MessageItem(
                    message = message,
                    onProductClick = { selectedProduct = it },
                    onAddToCart = onAddToCart
                )
            }
        }
    }
}

@Composable
private fun MessageItem(
    message: Message,
    onProductClick: (Product) -> Unit,
    onAddToCart: (Product) -> Unit
) {
    val isUser = message.role == MessageRole.User
    val alignment = if (isUser) Alignment.End else Alignment.Start

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = alignment
    ) {
        MessageBubble(message = message)
        if (message.compareTables.isNotEmpty()) {
            Spacer(modifier = Modifier.height(8.dp))
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                message.compareTables.forEach { table ->
                    CompareTableCard(table = table)
                }
            }
        }
        if (message.products.isNotEmpty()) {
            Spacer(modifier = Modifier.height(8.dp))
            LazyRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                contentPadding = PaddingValues(
                    start = if (isUser) 56.dp else 0.dp,
                    end = if (isUser) 0.dp else 40.dp
                )
            ) {
                items(message.products, key = { it.productId }) { product ->
                    ProductCard(
                        product = product,
                        onClick = { onProductClick(product) },
                        onAddToCart = { onAddToCart(product) }
                    )
                }
            }
        }
    }
}

@Composable
private fun MessageBubble(message: Message) {
    val isUser = message.role == MessageRole.User
    val background = when {
        message.isError -> MaterialTheme.colorScheme.errorContainer
        isUser -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.surfaceVariant
    }
    val contentColor = when {
        message.isError -> MaterialTheme.colorScheme.onErrorContainer
        isUser -> MaterialTheme.colorScheme.onPrimary
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }

    Surface(
        modifier = Modifier.widthIn(max = 320.dp),
        shape = RoundedCornerShape(
            topStart = 8.dp,
            topEnd = 8.dp,
            bottomStart = if (isUser) 8.dp else 2.dp,
            bottomEnd = if (isUser) 2.dp else 8.dp
        ),
        color = background,
        contentColor = contentColor
    ) {
        val text = when {
            message.content.isNotBlank() -> message.content
            message.status != null -> message.status
            message.isStreaming -> "正在整理推荐..."
            else -> ""
        }
        Text(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            text = text,
            style = MaterialTheme.typography.bodyLarge
        )
    }
}

@Composable
private fun CompareTableCard(table: CompareTable) {
    if (table.products.isEmpty() || table.rows.isEmpty()) {
        return
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                text = "商品对比",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface
            )
            Spacer(modifier = Modifier.height(8.dp))
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
            ) {
                CompareHeaderRow(table = table)
                table.rows.forEach { row ->
                    CompareBodyRow(table = table, dimension = row.dimension, values = row.values)
                }
            }
        }
    }
}

@Composable
private fun CompareHeaderRow(table: CompareTable) {
    Row(modifier = Modifier.height(IntrinsicSize.Min)) {
        CompareCell(
            text = "维度",
            width = 88.dp,
            isHeader = true
        )
        table.products.forEach { product ->
            CompareCell(
                text = product.title,
                width = 150.dp,
                isHeader = true
            )
        }
    }
}

@Composable
private fun CompareBodyRow(
    table: CompareTable,
    dimension: String,
    values: Map<String, String>
) {
    Row(modifier = Modifier.height(IntrinsicSize.Min)) {
        CompareCell(
            text = dimension,
            width = 88.dp,
            isHeader = true
        )
        table.products.forEach { product ->
            CompareCell(
                text = values[product.productId].orEmpty().ifBlank { "-" },
                width = 150.dp
            )
        }
    }
}

@Composable
private fun CompareCell(
    text: String,
    width: Dp,
    isHeader: Boolean = false
) {
    val background = if (isHeader) {
        MaterialTheme.colorScheme.surfaceVariant
    } else {
        MaterialTheme.colorScheme.surface
    }
    val textColor = if (isHeader) {
        MaterialTheme.colorScheme.onSurfaceVariant
    } else {
        MaterialTheme.colorScheme.onSurface
    }

    Box(
        modifier = Modifier
            .width(width)
            .fillMaxHeight()
            .border(0.5.dp, MaterialTheme.colorScheme.outlineVariant)
            .background(background)
            .padding(horizontal = 8.dp, vertical = 8.dp)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodySmall,
            fontWeight = if (isHeader) FontWeight.SemiBold else FontWeight.Normal,
            color = textColor
        )
    }
}

@Composable
private fun ProductCard(
    product: Product,
    onClick: () -> Unit,
    onAddToCart: () -> Unit
) {
    val priceText = remember(product.price) { formatPrice(product.price) }

    Card(
        modifier = Modifier
            .widthIn(min = 220.dp, max = 220.dp)
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            ProductImage(
                imageUrl = product.imageUrl,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1.35f)
                    .clip(RoundedCornerShape(6.dp))
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = product.title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(modifier = Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = priceText,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = product.brand ?: product.category,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Spacer(modifier = Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                AssistChip(
                    onClick = onClick,
                    label = {
                        Text(
                            text = product.subCategory ?: product.category,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                )
                IconButton(
                    modifier = Modifier.size(40.dp),
                    onClick = onAddToCart
                ) {
                    Icon(
                        imageVector = Icons.Default.AddShoppingCart,
                        contentDescription = "加入购物车",
                        tint = MaterialTheme.colorScheme.primary
                    )
                }
            }
        }
    }
}

@Composable
private fun ProductImage(
    imageUrl: String?,
    modifier: Modifier = Modifier
) {
    if (imageUrl == null) {
        Box(
            modifier = modifier.background(MaterialTheme.colorScheme.secondaryContainer),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = "暂无图片",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
        }
    } else {
        AsyncImage(
            model = imageUrl,
            contentDescription = null,
            modifier = modifier.background(MaterialTheme.colorScheme.surfaceVariant),
            contentScale = ContentScale.Crop
        )
    }
}

@Composable
private fun ChatInputBar(
    input: String,
    isLoading: Boolean,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onCancel: () -> Unit
) {
    Surface(
        tonalElevation = 3.dp,
        color = MaterialTheme.colorScheme.surface
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .imePadding()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedTextField(
                modifier = Modifier.weight(1f),
                value = input,
                onValueChange = onInputChange,
                placeholder = { Text("输入需求，例如：推荐一款适合油皮的洗面奶") },
                minLines = 1,
                maxLines = 4,
                enabled = !isLoading
            )
            if (isLoading) {
                IconButton(
                    modifier = Modifier.size(48.dp),
                    onClick = onCancel
                ) {
                    Icon(
                        imageVector = Icons.Default.Close,
                        contentDescription = "停止"
                    )
                }
            } else {
                IconButton(
                    modifier = Modifier.size(48.dp),
                    enabled = input.isNotBlank(),
                    onClick = onSend
                ) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.Send,
                        contentDescription = "发送"
                    )
                }
            }
        }
    }
}

@Composable
private fun ProductDialog(
    product: Product,
    onAddToCart: () -> Unit,
    onDismiss: () -> Unit
) {
    val priceText = remember(product.price) { formatPrice(product.price) }

    AlertDialog(
        onDismissRequest = onDismiss,
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("关闭")
            }
        },
        confirmButton = {
            Button(onClick = onAddToCart) {
                Icon(
                    imageVector = Icons.Default.AddShoppingCart,
                    contentDescription = null
                )
                Spacer(modifier = Modifier.width(6.dp))
                Text("加入购物车")
            }
        },
        title = { Text(product.title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                ProductImage(
                    imageUrl = product.imageUrl,
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(1.45f)
                        .clip(RoundedCornerShape(8.dp))
                )
                ProductInfoRow(label = "价格", value = priceText)
                product.brand?.let { ProductInfoRow(label = "品牌", value = it) }
                ProductInfoRow(label = "品类", value = product.category)
                product.subCategory?.let { ProductInfoRow(label = "细分", value = it) }
            }
        }
    )
}

@Composable
private fun CartSummaryBar(
    cart: Cart,
    cartError: String?,
    isCartLoading: Boolean,
    onClick: () -> Unit
) {
    val totalText = remember(cart.totalPrice) { formatPrice(cart.totalPrice) }
    val summaryText = cartError
        ?: cart.messages.firstOrNull()
        ?: "购物车 ${cart.totalQuantity} 件"
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        tonalElevation = 2.dp,
        color = MaterialTheme.colorScheme.primaryContainer,
        contentColor = MaterialTheme.colorScheme.onPrimaryContainer
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                modifier = Modifier.weight(1f),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Default.ShoppingCart,
                    contentDescription = null
                )
                Text(
                    text = summaryText,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Text(
                text = if (isCartLoading) "更新中" else totalText,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CartSheet(
    cart: Cart,
    isCartLoading: Boolean,
    cartError: String?,
    onDismiss: () -> Unit,
    onIncrement: (String) -> Unit,
    onDecrement: (String) -> Unit,
    onRemove: (String) -> Unit,
    onClear: () -> Unit
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "购物车",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        text = "${cart.totalQuantity} 件商品 · ${formatPrice(cart.totalPrice)}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                TextButton(
                    enabled = cart.items.isNotEmpty() && !isCartLoading,
                    onClick = onClear
                ) {
                    Text("清空")
                }
            }

            cartError?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }

            CartNoticeList(messages = cart.messages)

            if (cart.items.isEmpty()) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(160.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "购物车还是空的",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    cart.items.forEach { item ->
                        CartItemRow(
                            item = item,
                            enabled = !isCartLoading,
                            onIncrement = { onIncrement(item.productId) },
                            onDecrement = { onDecrement(item.productId) },
                            onRemove = { onRemove(item.productId) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun CartNoticeList(messages: List<String>) {
    if (messages.isEmpty()) {
        return
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.secondaryContainer)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        messages.forEach { message ->
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
        }
    }
}

@Composable
private fun CartItemRow(
    item: CartItem,
    enabled: Boolean,
    onIncrement: () -> Unit,
    onDecrement: () -> Unit,
    onRemove: () -> Unit
) {
    val statusText = item.unavailableReason
        ?: when {
            item.isActive == false -> "商品已下架"
            item.stock == 0 -> "库存不足"
            item.stock != null && item.quantity > item.stock -> "库存不足，仅剩 ${item.stock} 件"
            else -> null
        }
    val canAdjustQuantity = enabled && statusText == null

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier.padding(10.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            ProductImage(
                imageUrl = item.imageUrl,
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(6.dp))
            )
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text(
                    text = item.title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = "${formatPrice(item.price)} · 小计 ${formatPrice(item.subtotal)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                statusText?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        fontWeight = FontWeight.Medium
                    )
                }
                item.stock?.let { stock ->
                    if (statusText == null) {
                        Text(
                            text = "库存 $stock 件",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(
                        modifier = Modifier.size(32.dp),
                        enabled = canAdjustQuantity,
                        onClick = onDecrement
                    ) {
                        Icon(
                            imageVector = Icons.Default.Remove,
                            contentDescription = "减少"
                        )
                    }
                    Text(
                        text = item.quantity.toString(),
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold
                    )
                    IconButton(
                        modifier = Modifier.size(32.dp),
                        enabled = canAdjustQuantity,
                        onClick = onIncrement
                    ) {
                        Icon(
                            imageVector = Icons.Default.Add,
                            contentDescription = "增加"
                        )
                    }
                }
            }
            IconButton(
                enabled = enabled,
                onClick = onRemove
            ) {
                Icon(
                    imageVector = Icons.Default.Delete,
                    contentDescription = "删除",
                    tint = MaterialTheme.colorScheme.error
                )
            }
        }
    }
}

@Composable
private fun ProductInfoRow(
    label: String,
    value: String
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurface
        )
    }
}

private fun formatPrice(price: Double): String {
    return NumberFormat.getCurrencyInstance(Locale.CHINA).format(price)
}
