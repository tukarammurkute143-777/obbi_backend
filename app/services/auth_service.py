from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

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


def verify_google_id_token(token: str) -> dict:
    """
    Validate a Google ID token and return its claims.

    verify_oauth2_token checks the signature against Google's public certs, the
    exp/iat window, and that `iss` is a Google issuer. It only checks `aud` when
    an audience is passed, which is why GOOGLE_CLIENT_ID is mandatory above.
    Raises ValueError / GoogleAuthError on anything invalid.
    """
    return google_id_token.verify_oauth2_token(
        token,
        google_requests.Request(),
        settings.GOOGLE_CLIENT_ID,
    )


async def google_auth(
    token: str,
    ip: str,
    device_fingerprint: str = None,
    location: str = None
) -> dict:
    # Refuse to run unconfigured rather than verify tokens without an audience,
    # which would accept any Google account signed in to any other application.
    if not settings.GOOGLE_CLIENT_ID.strip():
        return {
            'success': False,
            'status': 503,
            'message': 'Google login abhi configure nahi hua.'
        }

    if check_ip_blocked(ip):
        return {
            'success': False,
            'status': 403,
            'message': 'Access blocked. Contact support.'
        }

    try:
        claims = verify_google_id_token(token)
    except Exception:
        # Covers bad signature, expired token, wrong audience and wrong issuer.
        # The reason is deliberately not echoed back to the caller.
        db.table('login_attempts').insert({
            'ip_address': ip,
            'login_type': 'google',
            'success': False
        }).execute()
        return {'success': False, 'message': 'Google token invalid hai.'}

    email = (claims.get('email') or '').strip().lower()
    if not email:
        return {'success': False, 'message': 'Google account mein email nahi mila.'}

    # google-auth does not check this. Without it, anyone able to attach an
    # unverified address to a Google account could claim an existing user's row.
    if not claims.get('email_verified'):
        return {
            'success': False,
            'message': 'Pehle apna Google email verify karo.'
        }

    if check_multi_account(ip, email):
        block_ip(ip, 'Multi-account detected')
        return {
            'success': False,
            'status': 403,
            'message': 'Suspicious activity detected'
        }

    # Match on email so a mobile-OTP user who later added the same address keeps
    # one account instead of getting a duplicate row.
    user_result = db.table('users')\
        .select('*')\
        .eq('email', email)\
        .execute()

    is_new_user = len(user_result.data) == 0

    if is_new_user:
        new_user = db.table('users').insert({
            'name': claims.get('name'),
            'email': email,
            'login_type': 'google',
            'location': location or 'Unknown',
            'is_new_user': True,
            'total_visits': 1
        }).execute()
        user = new_user.data[0]
    else:
        user = user_result.data[0]
        updates = {
            'last_login': datetime.utcnow().isoformat(),
            'total_visits': (user.get('total_visits') or 0) + 1,
            'is_new_user': False
        }
        # Fill in a name only if the row does not already have one, so a name
        # the user set themselves is never overwritten by their Google profile.
        if not user.get('name') and claims.get('name'):
            updates['name'] = claims['name']

        db.table('users').update(updates).eq('id', user['id']).execute()
        user = {**user, **updates}

    db.table('login_attempts').insert({
        'ip_address': ip,
        'email': email,
        'login_type': 'google',
        'success': True,
        'device_fingerprint': device_fingerprint
    }).execute()

    token_data = {'sub': str(user['id']), 'email': email}

    return {
        'success': True,
        'access_token': create_access_token(token_data),
        'refresh_token': create_refresh_token(token_data),
        'token_type': 'bearer',
        'user': user,
        'is_new_user': is_new_user
    }