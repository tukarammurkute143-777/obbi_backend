from app.core.config import settings
from app.core.database import db
from app.core.middleware import invalidate_ip_cache
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_otp
)
from datetime import datetime, timedelta
import re

# Store OTPs temporarily (Redis mein baad mein)
otp_store = {}

def validate_indian_mobile(mobile: str) -> bool:
    pattern = r'^[6-9]\d{9}$'
    return bool(re.match(pattern, mobile))

def check_ip_blocked(ip: str) -> bool:
    result = db.table('blocked_ips')\
        .select('id')\
        .eq('ip_address', ip)\
        .eq('is_active', True)\
        .execute()
    return len(result.data) > 0

def check_multi_account(ip: str, identifier: str) -> bool:
    """Check if same IP used with 2+ different accounts"""
    result = db.table('login_attempts')\
        .select('email, mobile')\
        .eq('ip_address', ip)\
        .eq('success', True)\
        .execute()
    
    identifiers = set()
    for r in result.data:
        if r.get('email'):
            identifiers.add(r['email'])
        if r.get('mobile'):
            identifiers.add(r['mobile'])
    
    identifiers.add(identifier)
    return len(identifiers) > 2

def block_ip(ip: str, reason: str):
    """Block suspicious IP"""
    db.table('blocked_ips').upsert({
        'ip_address': ip,
        'reason': reason,
        'is_active': True
    }).execute()
    # IPBlockMiddleware caches lookups for 60s; drop this IP's entry so the
    # block applies to the very next request instead of after the TTL.
    invalidate_ip_cache(ip)

async def send_otp(mobile: str, ip: str) -> dict:
    # Validate mobile
    if not validate_indian_mobile(mobile):
        return {'success': False, 'message': 'Valid Indian mobile number daalo'}
    
    # Check IP blocked
    if check_ip_blocked(ip):
        return {'success': False, 'message': 'Access blocked. Contact support.'}
    
    # Check multi-account fraud
    if check_multi_account(ip, mobile):
        block_ip(ip, 'Multi-account detected')
        return {'success': False, 'message': 'Suspicious activity detected'}
    
    # Generate OTP
    otp = generate_otp()
    
    # Store OTP (5 min expiry)
    otp_store[mobile] = {
        'otp': otp,
        'expires': datetime.utcnow() + timedelta(minutes=5),
        'attempts': 0
    }
    
    # Log attempt
    db.table('login_attempts').insert({
        'ip_address': ip,
        'mobile': mobile,
        'login_type': 'mobile',
        'success': False
    }).execute()
    
    # TODO: Send via WhatsApp API
    is_production = settings.APP_ENV.strip().lower() == 'production'

    if not is_production:
        # Both of these hand out the OTP for any number, so they are dev-only:
        # the response field lets the caller skip WhatsApp entirely, and the
        # log line would write every OTP into the hosting provider's logs.
        print(f"OTP for {mobile}: {otp}")

    response = {
        'success': True,
        'message': 'OTP sent on WhatsApp'
    }
    if not is_production:
        response['dev_otp'] = otp

    return response

async def verify_otp(
    mobile: str,
    otp: str,
    ip: str,
    device_fingerprint: str = None,
    location: str = None
) -> dict:
    # Check OTP exists
    stored = otp_store.get(mobile)
    if not stored:
        return {'success': False, 'message': 'OTP expired. Resend karo.'}
    
    # Check expiry
    if datetime.utcnow() > stored['expires']:
        del otp_store[mobile]
        return {'success': False, 'message': 'OTP expire ho gaya. Resend karo.'}
    
    # Check attempts
    if stored['attempts'] >= 3:
        del otp_store[mobile]
        return {'success': False, 'message': 'Too many attempts. Resend karo.'}
    
    # Verify OTP
    if stored['otp'] != otp:
        otp_store[mobile]['attempts'] += 1
        return {'success': False, 'message': 'Galat OTP hai.'}
    
    # OTP correct — clean up
    del otp_store[mobile]
    
    # Get or create user
    user_result = db.table('users')\
        .select('*')\
        .eq('mobile', mobile)\
        .execute()
    
    is_new_user = len(user_result.data) == 0
    
    if is_new_user:
        new_user = db.table('users').insert({
            'mobile': mobile,
            'login_type': 'mobile',
            'location': location or 'Unknown',
            'is_new_user': True,
            'total_visits': 1
        }).execute()
        user = new_user.data[0]
    else:
        user = user_result.data[0]
        # Update visit count
        db.table('users').update({
            'last_login': datetime.utcnow().isoformat(),
            'total_visits': user['total_visits'] + 1,
            'is_new_user': False
        }).eq('id', user['id']).execute()
    
    # Update login attempt
    db.table('login_attempts').update({
        'success': True,
        'device_fingerprint': device_fingerprint
    }).eq('mobile', mobile)\
      .eq('ip_address', ip)\
      .execute()
    
    # Create tokens
    token_data = {'sub': str(user['id']), 'mobile': mobile}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    
    return {
        'success': True,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'bearer',
        'user': user,
        'is_new_user': is_new_user
    }