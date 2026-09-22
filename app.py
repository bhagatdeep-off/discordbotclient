import os
import threading
import asyncio
from flask import Flask, render_template_string, jsonify, request
import discord

app = Flask(__name__)

# Fetch configuration from Railway Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Set up Discord Client Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

client = discord.Client(intents=intents)
loop = asyncio.new_event_loop()

# ----------------- Discord Bot Logic -----------------
def run_discord_bot():
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(client.start(BOT_TOKEN))
    except Exception as e:
        print(f"Error starting bot: {e}")

# Start the bot in a background thread so it doesn't block Flask
threading.Thread(target=run_discord_bot, daemon=True).start()

# ----------------- Flask Web API Routes -----------------

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Custom Discord Bot Client</title>
    <style>
        body { margin: 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #36393f; color: #dcddde; display: flex; height: 100vh; overflow: hidden; }
        .sidebar { width: 260px; background-color: #2f3136; display: flex; flex-direction: column; border-right: 1px solid #202225; }
        .header { padding: 15px; font-weight: bold; font-size: 16px; background-color: #2f3136; border-bottom: 1px solid #202225; color: #fff; }
        .channel-list { flex: 1; overflow-y: auto; padding: 10px; }
        .channel-item { padding: 8px 10px; border-radius: 4px; margin-bottom: 2px; cursor: pointer; color: #8e9297; }
        .channel-item:hover, .channel-item.active { background-color: #34373c; color: #dcddde; }
        .chat-area { flex: 1; display: flex; flex-direction: column; background-color: #36393f; }
        .messages { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .message { display: flex; flex-direction: column; }
        .msg-author { font-weight: bold; color: #fff; margin-bottom: 2px; font-size: 14px; }
        .msg-content { color: #dcddde; font-size: 15px; }
        .input-area { padding: 20px; background-color: #36393f; }
        .input-box { width: 100%; padding: 15px; background-color: #40444b; border: none; border-radius: 8px; color: #dcddde; font-size: 15px; box-sizing: border-box; }
        .input-box:focus { outline: none; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="header">Text Channels</div>
        <div class="channel-list" id="channels">Loading channels...</div>
    </div>
    <div class="chat-area">
        <div class="header" id="current-channel">Select a channel</div>
        <div class="messages" id="message-container"></div>
        <div class="input-area">
            <input type="text" class="input-box" id="msg-input" placeholder="Message #channel" disabled>
        </div>
    </div>

    <script>
        let activeChannelId = null;

        // Fetch visible channels from the backend
        async function loadChannels() {
            const res = await fetch('/api/channels');
            const channels = await res.json();
            const list = document.getElementById('channels');
            list.innerHTML = '';
            
            channels.forEach(ch => {
                const div = document.createElement('div');
                div.className = 'channel-item';
                div.innerText = `# ${ch.name} (${ch.guild})`;
                div.onclick = () => selectChannel(ch.id, ch.name);
                list.appendChild(div);
            });
        }

        // Switch active channel view
        async function selectChannel(id, name) {
            activeChannelId = id;
            document.getElementById('current-channel').innerText = `# ${name}`;
            const input = document.getElementById('msg-input');
            input.placeholder = `Message #${name}`;
            input.disabled = false;
            
            // Highlight active element
            document.querySelectorAll('.channel-item').forEach(el => el.classList.remove('active'));
            event.target.classList.add('active');
            
            loadMessages();
        }

        // Pull historical messages for the active channel
        async function loadMessages() {
            if (!activeChannelId) return;
            const res = await fetch(`/api/messages?channel_id=${activeChannelId}`);
            const messages = await res.json();
            const container = document.getElementById('message-container');
            container.innerHTML = '';
            
            messages.forEach(msg => {
                const div = document.createElement('div');
                div.className = 'message';
                div.innerHTML = `<span class="msg-author">${msg.author}</span><span class="msg-content">${msg.content}</span>`;
                container.appendChild(div);
            });
            container.scrollTop = container.scrollHeight;
        }

        // Handle typing and hitting Enter to send
        document.getElementById('msg-input').addEventListener('keypress', async function(e) {
            if (e.key === 'Enter' && this.value.trim() !== '' && activeChannelId) {
                const content = this.value;
                this.value = '';
                
                await fetch('/api/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ channel_id: activeChannelId, content: content })
                });
                
                setTimeout(loadMessages, 500); // Give it a brief moment to update
            }
        });

        // Initialize and poll for new messages every 3 seconds
        loadChannels();
        setInterval(loadMessages, 3000);
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/channels')
def get_channels():
    # Gather all text channels the bot has permission to see
    channels = []
    if client.is_ready():
        for guild in client.guilds:
            for channel in guild.text_channels:
                channels.append({
                    "id": channel.id,
                    "name": channel.name,
                    "guild": guild.name
                })
    return jsonify(channels)

@app.route('/api/messages')
def get_messages():
    channel_id = request.args.get('channel_id')
    if not channel_id or not client.is_ready():
        return jsonify([])
        
    channel = client.get_channel(int(channel_id))
    if not channel:
        return jsonify([])

    # Asynchronously grab the last 20 messages from the history logs
    future = asyncio.run_coroutine_threadsafe(channel.history(limit=20).flatten(), loop)
    try:
        history = future.result(timeout=5)
        # Reverse to keep chronological order (oldest to newest)
        return jsonify([{"author": msg.author.name, "content": msg.content} for msg in reversed(history)])
    except Exception:
        return jsonify([])

@app.route('/api/send', mode=['POST'])
def send_message():
    data = request.json
    channel_id = data.get('channel_id')
    content = data.get('content')
    
    if channel_id and content and client.is_ready():
        channel = client.get_channel(int(channel_id))
        if channel:
            asyncio.run_coroutine_threadsafe(channel.send(content), loop)
            return jsonify({"status": "success"})
            
    return jsonify({"status": "error"}), 400

if __name__ == '__main__':
    # Standard dynamic port checking for local testing and cloud deployments
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
