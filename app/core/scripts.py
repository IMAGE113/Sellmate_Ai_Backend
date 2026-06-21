"""
Centralized Script Management for SellMate AI
Stores all Myanmar response templates mapped to status keys.
"""

SCRIPTS_MAP = {
    # Greeting & Initial Interaction
    "GREETING": "မင်္ဂလာပါရှင်၊ {shop_name} မှ ကြိုဆိုပါတယ်။ ဘာပစ္စည်းလေး မှာယူချင်ပါသလဲ ရှင့်။ 🙏",
    "MENU_INFO": "ပစ္စည်းအပြည့်အစုံကို Page Post ထဲမှာ တင်ပေးထားပါတယ်ရှင် 💙",
    
    # Information Gathering
    "ASK_NAME": "ဟုတ်ကဲ့ပါရှင်။ မှာယူသူရဲ့ 'အမည်' လေး ပြောပေးပါဦးရှင်။",
    "ASK_PHONE": "ဟုတ်ကဲ့ပါရှင်။ ဆက်သွယ်ရမယ့် 'ဖုန်းနံပါတ်' လေး ပြောပေးပါဦးရှင်။",
    "ASK_ADDRESS": "ဟုတ်ကဲ့ပါရှင်။ ပစ္စည်းပို့ပေးရမယ့် 'လိပ်စာ' အပြည့်အစုံလေး ပြောပေးပါဦးရှင်။",
    "ASK_TOWNSHIP": "ဟုတ်ကဲ့ပါရှင်။ မြို့နယ် (Township) လေး ပြောပေးပါဦးရှင်။",
    "ASK_SIZE": "ပစ္စည်းအတွက် 'ဆိုဒ် (Size)' လေး ဘယ်လောက်ယူမလဲရှင်။",
    "ASK_COLOR": "ပစ္စည်းအတွက် 'အရောင် (Color)' လေး ဘာယူမလဲရှင်။",
    "ASK_QUANTITY": "အရေအတွက် ဘယ်လောက်ယူမလဲရှင်။",
    
    # Payment Flow
    "ASK_PAYMENT_METHOD": "ငွေပေးချေမှုကို 'COD (ပစ္စည်းရောက်ငွေချေ)' လား 'Prepaid (ကြိုတင်ငွေလွှဲ)' လား ဘယ်လိုလုပ်မလဲရှင်။",
    "ASK_PAYMENT_SCREENSHOT": "ဟုတ်ကဲ့ပါရှင်။ ငွေလွှဲပြီးရင် 'ငွေလွှဲပြေစာ (Screenshot)' လေး ဒီမှာ ပို့ပေးပါဦးရှင်။",
    "PAYMENT_RECEIVED_WAITING_REVIEW": "ငွေလွှဲပြေစာ ရရှိပါပြီရှင်။ ဆိုင်က Admin မှ စစ်ဆေးပြီးတာနဲ့ အော်ဒါကို အတည်ပြုပေးပါမယ်ရှင်။ ခဏလေး စောင့်ပေးပါဦးနော်။ 🙏",
    
    # Confirmation & Completion
    "ORDER_CONFIRMED": "အော်ဒါကို အတည်ပြုလိုက်ပါပြီ။ ကျေးဇူးအများကြီးတင်ပါတယ်ရှင်! 🙏",
    "ORDER_READY_TO_SHIP": "လူကြီးမင်းရဲ့ အော်ဒါကို ပို့ဆောင်ဖို့ ပြင်ဆင်နေပါပြီရှင်။",
    "ORDER_COMPLETED": "အော်ဒါ ပို့ဆောင်ပြီးစီးပါပြီ။ နောက်လည်း အားပေးပါဦးရှင်။ 🙏",
    "ORDER_CANCELLED": "စိတ်မကောင်းပါဘူးရှင်။ လူကြီးမင်းရဲ့ အော်ဒါကို ဖျက်သိမ်းလိုက်ပါပြီ။",
    
    # Fallbacks & Special States
    "FALLBACK": "နားမလည်လို့ ပြန်ပြောပေးပါဦးရှင်။ အော်ဒါအတွက် လိုအပ်တဲ့ အချက်အလက်လေးတွေ ပြောပေးပါနော်။",
    "HUMAN_TAKEOVER": "ဟုတ်ကဲ့ပါရှင်။ အခု AI စနစ်ကို ခေတ္တပိတ်ပေးထားပြီး ဆိုင်က လူကြီးမင်း (Admin) ကို လှမ်းခေါ်ပေးနေပါပြီ။ ခဏလေး စောင့်ပေးပေးပါဦးရှင်။ 🙋‍♂️",
    "OUT_OF_STOCK": "စိတ်မကောင်းပါဘူးရှင်။ မှာယူလိုက်တဲ့ ပစ္စည်းက လက်ရှိ စတော့ကုန်သွားလို့ မှာယူလို့ မရနိုင်တော့ပါဘူးရှင်။ 🙇‍♂️"
}

def get_script(status_key: str, **kwargs) -> str:
    """
    Retrieve and format a response script by status key.
    """
    template = SCRIPTS_MAP.get(status_key, SCRIPTS_MAP["FALLBACK"])
    try:
        return template.format(**kwargs)
    except KeyError:
        return template
