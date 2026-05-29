from flask import Flask, request, jsonify
import json, os, aiohttp, asyncio, requests, binascii, random
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import like_pb2, like_count_pb2, uid_generator_pb2
from google.protobuf.message import DecodeError

app = Flask(__name__)

# ✅ Only India Server ke liye files ke paths
LIKES_TOKENS_FILE = 'token_ind.json'
VISIT_TOKENS_FILE = 'visit_ind.json'

# ✅ Files se tokens load karne ka function
def get_tokens_from_file(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                tokens = [item["token"] for item in data if "token" in item]
                return tokens
        except Exception as e:
            app.logger.error(f"Error reading token file ({file_path}): {e}")
            return []
    return []

# ✅ Encryption & Protobuf Helper Functions
def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode()
    except Exception as e:
        app.logger.error(f"Encryption failed: {e}")
        return None

def create_uid_proto(uid):
    try:
        pb = uid_generator_pb2.uid_generator()
        pb.saturn_ = int(uid)
        pb.garena = 1
        return pb.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None

def create_like_proto(uid):
    try:
        pb = like_pb2.like()
        pb.uid = int(uid)
        return pb.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating like protobuf: {e}")
        return None

def decode_protobuf(binary):
    try:
        pb = like_count_pb2.Info()
        pb.ParseFromString(binary)
        return pb
    except DecodeError:
        return None

# ✅ Profile Visit (Ek Random token use karke profile read karega)
def make_request(enc_uid, token):
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB53"
    }
    try:
        res = requests.post(url, data=bytes.fromhex(enc_uid), headers=headers, verify=False, timeout=15)
        return decode_protobuf(res.content)
    except Exception as e:
        app.logger.error(f"Error in profile visit request: {e}")
        return None

# ✅ Send Request (Ab session create nahi karega, main pool se reuse karega)
async def send_request(session, enc_uid, token, url):
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB53"
    }
    try:
        # Reusing the dynamic session passed from the loop
        async with session.post(url, data=bytes.fromhex(enc_uid), headers=headers, ssl=False) as r:
            return r.status
    except Exception as e:
        app.logger.error(f"Exception in send_request for token {token[:10]}...: {e}")
        return None

# ✅ Direct Send (Batching poori tarah se khatam, direct execution)
async def send_multiple_likes(uid, tokens, url):
    protobuf_data = create_like_proto(uid)
    if protobuf_data is None:
        return []
        
    enc_uid = encrypt_message(protobuf_data)
    if enc_uid is None:
        return []
    
    # Max 215 tokens filter karega bina duplicate select kiye
    target_limit = min(len(tokens), 215)
    selected_tokens = random.sample(tokens, target_limit)
    
    responses = []
    
    # Ek baar main single session generate kiya taaki connection reuse ho sake
    async with aiohttp.ClientSession() as session:
        # Saare 215 tasks ek sath queue honge bina kisi delay ke
        tasks = [send_request(session, enc_uid, token, url) for token in selected_tokens]
        
        # Ek hi jhatke me direct saari requests parallel jayengi
        batch_responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in batch_responses:
            if isinstance(res, int):
                responses.append(res)
            else:
                responses.append(None)
                
    return responses

# ✅ Main Route / Endpoint (Focus strictly on India)
@app.route('/like', methods=['GET'])
def handle_requests():
    uid = request.args.get("uid")
    if not uid:
        return jsonify({"error": "UID is required"}), 400

    try:
        # 1️⃣ Tokens file se read karna
        visit_tokens = get_tokens_from_file(VISIT_TOKENS_FILE)
        like_tokens = get_tokens_from_file(LIKES_TOKENS_FILE)
        
        if not visit_tokens or not like_tokens:
            return jsonify({"error": "Required token files are missing or empty"}), 401

        # Profile check data structure ready karna
        random_visit_token = random.choice(visit_tokens)
        enc_uid_visit = encrypt_message(create_uid_proto(uid))
        if not enc_uid_visit:
            return jsonify({"error": "UID Encryption failed"}), 500
            
        # Likes se pehle ka status fetch karna (Before)
        before = make_request(enc_uid_visit, random_visit_token)
        if before is None:
            return jsonify({"error": "Failed to retrieve initial player info from server"}), 500
            
        data_before = json.loads(MessageToJson(before))
        before_like = int(data_before.get('AccountInfo', {}).get('Likes', 0))
        player_name = str(data_before.get('AccountInfo', {}).get('PlayerNickname', 'Unknown'))

        # Dedicated India Region Like Endpoint
        url = "https://client.ind.freefiremobile.com/LikeProfile"

        # 2️⃣ Direct Parallel Bombing Execution (No Batches)
        responses = asyncio.run(send_multiple_likes(uid, like_tokens, url))
        success_count = sum(1 for r in responses if r == 200)

        # Likes ke baad ka status check karna (After)
        random_visit_token_after = random.choice(visit_tokens)
        after = make_request(enc_uid_visit, random_visit_token_after)
        
        after_like = before_like
        if after is not None:
            data_after = json.loads(MessageToJson(after))
            after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0))
            
        like_given = after_like - before_like
        status = 1 if like_given != 0 else 2
        actual_total_sent = min(len(like_tokens), 215)
        
        return jsonify({
            "DEVELOPER TELEGRAM": "@SEMY0HERE",
            "LikesGivenByAPI": like_given,
            "LikesAfterCommand": after_like,
            "LikesBeforeCommand": before_like,
            "PlayerNickname": player_name,
            "SuccessfulRequests": success_count,
            "TotalRequests": actual_total_sent,
            "UID": int(uid),
            "status": status
        })

    except Exception as e:
        app.logger.error(f"Error processing endpoint logic: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Direct High-Success India Like API is ready! 🚀"})

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)
    app.run(host='0.0.0.0', port=3000, debug=True, use_reloader=False)
