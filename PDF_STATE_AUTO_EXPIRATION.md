# Complete PDF State Lifecycle - Intelligent Auto-Expiration

## 🎯 **REQUIREMENT**

**User's Insight:** "It's not necessary that user always explicitly rejects PDF by sending a negative message, the user could also just move on to the next query"

**Solution:** Automatically invalidate pending PDF offers when user moves on to ANY other message type.

---

## 📊 **PDF STATE LIFECYCLE**

### **4 States:**

1. **`pending_pdf_request`** - PDF offered, awaiting user response
2. **`pdf_fulfilled`** - User said yes, PDF sent ✅
3. **`pdf_declined`** - User explicitly said no ❌
4. **`pdf_expired`** - User moved on (new query/greeting/irrelevant) ⏱️

---

## 🔄 **STATE TRANSITION LOGIC**

### **State Machine:**

```
┌─────────────────────────────────────┐
│     LEGAL QUERY COMPLETED           │
│     Research Done                   │
└──────────────┬──────────────────────┘
               ↓
    ┌──────────────────────┐
    │ State:               │
    │ "pending_pdf_request"│
    │ (Waiting for user)   │
    └──────────┬───────────┘
               ↓
    ┌──────────────────────────────────────────────┐
    │           USER RESPONSE                      │
    └───┬────────┬────────┬──────────┬────────┬────┘
        ↓        ↓        ↓          ↓        ↓
    ┌────────┐ ┌─────┐ ┌──────┐ ┌─────────┐ ┌─────────┐
    │ "Yes"  │ │"No" │ │Legal │ │Greeting │ │Irrelevant│
    │(short) │ │     │ │Query │ │"Hi"     │ │"Weather"│
    └───┬────┘ └──┬──┘ └───┬──┘ └────┬────┘ └────┬────┘
        ↓         ↓        ↓         ↓           ↓
    ┌─────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
    │fulfilled│ │declined│ │expired │ │expired │ │expired │
    │         │ │        │ │        │ │        │ │        │
    │Send PDF │ │Friendly│ │Process │ │Respond │ │Decline │
    │         │ │Message │ │New     │ │to      │ │Politely│
    │         │ │        │ │Query   │ │Greeting│ │        │
    └─────────┘ └────────┘ └────────┘ └────────┘ └────────┘
```

---

## 💻 **IMPLEMENTATION**

### **1. Auto-Expire on New Legal Query**

**Location:** `llm_service.py` line ~443

**Code:**
```python
# STEP 4: If not a PDF request, process as NEW LEGAL QUERY
# ✅ IMPORTANT: Automatically invalidate any old pending PDF offers
if chat_history and len(chat_history) > 0:
    try:
        for msg in reversed(chat_history):
            if msg.get('role') == 'model' and 'research_data' in msg:
                old_state = msg['research_data'].get('type')
                if old_state == 'pending_pdf_request':
                    msg['research_data']['type'] = 'pdf_expired'
                    logger.info("🔄 Invalidated old pending PDF - user moved to new query")
                break
        store_chat(wa_id, chat_history)
    except Exception as e:
        logger.warning(f"⚠️ Could not invalidate old PDF state: {e}")

# Now process the new legal query
logger.info(f"⚖️ Processing new legal query...")
```

### **2. Auto-Expire on Chitchat**

**Location:** `llm_service.py` line ~370

**Code:**
```python
if message_type == "CHITCHAT":
    logger.info(f"💬 Chitchat detected...")
    
    # Invalidate any pending PDF offer
    chat_history = check_if_chat_exists(wa_id)
    if chat_history and len(chat_history) > 0:
        try:
            for msg in reversed(chat_history):
                if msg.get('role') == 'model' and 'research_data' in msg:
                    if msg['research_data'].get('type') == 'pending_pdf_request':
                        msg['research_data']['type'] = 'pdf_expired'
                        logger.info("🔄 Invalidated pending PDF - user sent chitchat")
                    break
            store_chat(wa_id, chat_history)
        except Exception as e:
            logger.warning(f"⚠️ Could not invalidate PDF state: {e}")
    
    return _handle_chitchat(message, wa_id, name)
```

### **3. Auto-Expire on Irrelevant Query**

**Location:** `llm_service.py` line ~390

**Code:**
```python
elif message_type == "IRRELEVANT":
    logger.info(f"🚫 Irrelevant query detected...")
    
    # Invalidate any pending PDF offer
    chat_history = check_if_chat_exists(wa_id)
    if chat_history and len(chat_history) > 0:
        try:
            for msg in reversed(chat_history):
                if msg.get('role') == 'model' and 'research_data' in msg:
                    if msg['research_data'].get('type') == 'pending_pdf_request':
                        msg['research_data']['type'] = 'pdf_expired'
                        logger.info("🔄 Invalidated pending PDF - user sent irrelevant")
                    break
            store_chat(wa_id, chat_history)
        except Exception as e:
            logger.warning(f"⚠️ Could not invalidate PDF state: {e}")
    
    return _handle_irrelevant(message, wa_id, name)
```

### **4. Explicit Decline**

**Location:** `llm_service.py` line ~720

**Code:**
```python
def _handle_pdf_rejection(wa_id: str, detected_language: str) -> str:
    # ✅ CLEAR PENDING PDF STATE - Mark as declined
    try:
        chat_history = check_if_chat_exists(wa_id)
        if chat_history and len(chat_history) > 0:
            for msg in reversed(chat_history):
                if msg.get('role') == 'model' and 'research_data' in msg:
                    msg['research_data']['type'] = 'pdf_declined'
                    break
            store_chat(wa_id, chat_history)
            logger.info("✅ Marked PDF state as declined")
    except Exception as e:
        logger.error(f"Error updating PDF rejection status: {e}")
```

### **5. Explicit Acceptance**

**Location:** `llm_service.py` line ~405

**Code:**
```python
# Generate PDF
pdf_path = generate_pdf_report(wa_id, name, research_data)

# ✅ CLEAR PENDING PDF STATE - Mark as fulfilled
try:
    research_data['type'] = 'pdf_fulfilled'
    for msg in reversed(chat_history):
        if msg.get('role') == 'model' and 'research_data' in msg:
            msg['research_data']['type'] = 'pdf_fulfilled'
            break
    store_chat(wa_id, chat_history)
    logger.info("✅ Marked PDF state as fulfilled")
except Exception as e:
    logger.warning(f"⚠️ Could not update PDF state: {e}")
```

---

## 🧪 **TEST SCENARIOS**

### **Scenario 1: User Moves to New Legal Query** ✅

```
User: "What is bail in Pakistan?"
Bot: [Legal response] + "Would you like a detailed PDF report?"
State: "pending_pdf_request"

User: "What about property law in Pakistan?"
Action: 
  1. Classify as LEGAL ✅
  2. Invalidate old PDF state → "pdf_expired" ✅
  3. Process new legal query ✅
  4. Create NEW pending offer ✅

Result: 
  - Old PDF offer: EXPIRED
  - New legal research: COMPLETED
  - New PDF offer: CREATED
```

### **Scenario 2: User Sends Greeting** ✅

```
User: "What is bail in Pakistan?"
Bot: [Legal response] + "Would you like a detailed PDF report?"
State: "pending_pdf_request"

User: "Thanks for the info!"
Action:
  1. Classify as CHITCHAT ✅
  2. Invalidate PDF state → "pdf_expired" ✅
  3. Send friendly response ✅

Result:
  - Old PDF offer: EXPIRED
  - Bot: "You're welcome! Let me know if you need anything else."
```

### **Scenario 3: User Asks Irrelevant Question** ✅

```
User: "What is bail in Pakistan?"
Bot: [Legal response] + "Would you like a detailed PDF report?"
State: "pending_pdf_request"

User: "What's the weather today?"
Action:
  1. Classify as IRRELEVANT ✅
  2. Invalidate PDF state → "pdf_expired" ✅
  3. Send polite decline ✅

Result:
  - Old PDF offer: EXPIRED
  - Bot: "I'm a legal assistant, I can only help with law questions"
```

### **Scenario 4: User Explicitly Says No** ✅

```
User: "What is bail in Pakistan?"
Bot: [Legal response] + "Would you like a detailed PDF report?"
State: "pending_pdf_request"

User: "No thanks"
Action:
  1. Check: has_pending_pdf_offer = True ✅
  2. Check: _is_pdf_rejection() = True ✅
  3. Mark state → "pdf_declined" ✅
  4. Send friendly acknowledgment ✅

Result:
  - Old PDF offer: DECLINED
  - Bot: "No problem! Feel free to ask more questions."
```

### **Scenario 5: User Says Yes** ✅

```
User: "What is bail in Pakistan?"
Bot: [Legal response] + "Would you like a detailed PDF report?"
State: "pending_pdf_request"

User: "Yes"
Action:
  1. Check: has_pending_pdf_offer = True ✅
  2. Check: is_short_response (≤5 words) = True ✅
  3. Check: _is_pdf_request() = True ✅
  4. Generate PDF ✅
  5. Mark state → "pdf_fulfilled" ✅
  6. Send PDF ✅

Result:
  - Old PDF offer: FULFILLED
  - PDF: SENT
```

---

## 📋 **STATE VERIFICATION LOGIC**

### **Before Processing ANY Message:**

```python
# Check if there's a pending PDF offer
has_pending_pdf_offer = False

chat_history = check_if_chat_exists(wa_id)
if chat_history:
    for msg in reversed(chat_history):
        if msg.get('role') == 'model' and 'research_data' in msg:
            research_data = msg['research_data']
            # ONLY consider it pending if state is EXACTLY "pending_pdf_request"
            if research_data.get('type') == 'pending_pdf_request':
                has_pending_pdf_offer = True
            break

# Now decide what to do based on message type AND pending state
```

---

## 🎯 **KEY BENEFITS**

### **1. Natural Conversation Flow**
- ✅ User doesn't need to explicitly reject
- ✅ Moving on = implicit rejection
- ✅ No lingering old offers

### **2. No False Positives**
- ✅ "when **can** a tenant..." → NOT treated as rejection
- ✅ Only checks rejection when state is `pending_pdf_request`
- ✅ New queries invalidate old offers automatically

### **3. Clean State Management**
- ✅ Every query gets its own PDF offer
- ✅ Old offers don't interfere with new queries
- ✅ Clear audit trail in logs

### **4. User-Friendly**
- ✅ No pressure to respond to PDF offer
- ✅ Can ask new questions freely
- ✅ PDF offer doesn't block conversation

---

## 📊 **STATE DISTRIBUTION (Expected)**

Based on typical user behavior:

```
pending_pdf_request: ~10%  (actively waiting)
pdf_fulfilled:       ~15%  (user said yes)
pdf_declined:        ~5%   (user said no)
pdf_expired:         ~70%  (user moved on)
```

Most users will simply move on to next query without explicitly accepting/rejecting.

---

## 🔍 **LOGGING**

All state transitions are logged:

```python
# Creation
logger.info("✅ PDF offer created - state: pending_pdf_request")

# Fulfillment
logger.info("✅ Marked PDF state as fulfilled")

# Explicit Decline
logger.info("✅ Marked PDF state as declined")

# Auto-Expiration
logger.info("🔄 Invalidated old pending PDF - user moved to new query")
logger.info("🔄 Invalidated pending PDF - user sent chitchat")
logger.info("🔄 Invalidated pending PDF - user sent irrelevant query")
```

---

## ✅ **VERIFICATION CHECKLIST**

To verify the implementation works:

- [ ] Legal Query → PDF Offer → New Legal Query → Old offer expired ✅
- [ ] Legal Query → PDF Offer → Greeting → Old offer expired ✅
- [ ] Legal Query → PDF Offer → Irrelevant → Old offer expired ✅
- [ ] Legal Query → PDF Offer → "No" → State: declined ✅
- [ ] Legal Query → PDF Offer → "Yes" → PDF sent, State: fulfilled ✅
- [ ] No false positives on "can", "when", etc. ✅

---

## 🚀 **FUTURE ENHANCEMENTS**

### **1. Time-Based Expiration** (Optional)
```python
# Auto-expire after 10 minutes
import time
research_data['offer_timestamp'] = time.time()

# On new message:
if time.time() - research_data.get('offer_timestamp', 0) > 600:  # 10 min
    research_data['type'] = 'pdf_expired_timeout'
```

### **2. Re-offer Capability** (Optional)
```python
# Allow user to request PDF from expired offer
if message.lower() in ['send that pdf', 'i want the pdf now']:
    # Check for most recent expired offer
    # Re-generate PDF from stored research_data
```

### **3. Analytics** (Optional)
```python
# Track state distribution
states = {
    'fulfilled': 0,
    'declined': 0,
    'expired': 0
}
# Log to analytics service
```

---

**Status:** FULLY IMPLEMENTED ✅  
**Auto-Expiration:** ACTIVE ✅  
**Natural Flow:** PRESERVED ✅  
**State Management:** COMPLETE ✅

**Last Updated:** October 7, 2025
