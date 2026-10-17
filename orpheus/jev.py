"""Bounded System One Choice transport; no task-model fallback."""
import asyncio
import json
import math
import aiohttp
from .resolver import SelectionError
from .deployment import DEFAULT_JEV_ENDPOINT, validate_jev_endpoint


class JevClient:
    def __init__(self, token, session=None, *, endpoint=DEFAULT_JEV_ENDPOINT):
        self.endpoint=validate_jev_endpoint(endpoint)
        self.token=token
        self.session=session

    async def choose(self, *, model, state, choices, timeout=10, min_confidence=None):
        if not self.token: raise SelectionError('Missing Jev credential','missing_credentials')
        if not choices or len(choices)>255: raise SelectionError('Invalid choice count','invalid_config')
        payload={'model':model,'state':state,'questions':{'selection':{'type':'choice','instructions':'Select the most suitable configured execution option for the supplied task.', 'criteria':choices}}}
        session=self.session or aiohttp.ClientSession()
        try:
            async with session.post(self.endpoint,json=payload,headers={'Authorization':'Bearer '+self.token},timeout=aiohttp.ClientTimeout(total=timeout),allow_redirects=False) as response:
                if response.status in (401,403): raise SelectionError('Jev authentication failed','authentication_failed')
                if response.status==429: raise SelectionError('Jev rate limited','rate_limited')
                if response.status>=500: raise SelectionError('Jev unavailable','service_unavailable')
                if response.status!=200: raise SelectionError('Invalid Jev response','invalid_response')
                raw=await response.content.read(65537)
                if len(raw)>65536: raise SelectionError('Oversized Jev response','invalid_response')
                try: data=json.loads(raw)
                except (ValueError,UnicodeDecodeError) as exc: raise SelectionError('Malformed Jev response','invalid_response') from exc
                return self.validate(data,choices,min_confidence)
        except asyncio.TimeoutError as exc: raise SelectionError('Jev timeout','timeout') from exc
        except aiohttp.ClientError: raise SelectionError('Jev transport unavailable','service_unavailable') from None
        finally:
            if self.session is None: await session.close()

    @staticmethod
    def validate(data,choices,min_confidence=None):
        answers=data.get('answers') if isinstance(data,dict) else None
        if not isinstance(answers,dict) or set(answers)!={'selection'} or not isinstance(answers['selection'],dict): raise SelectionError('Invalid Jev answer shape','invalid_response')
        answer=answers['selection']
        if answer.get('type')!='choice' or not isinstance(answer.get('choice'), str) or answer['choice'] not in choices: raise SelectionError('Invalid Jev choice','invalid_response')
        probabilities=answer.get('probabilities')
        if not isinstance(probabilities,dict) or set(probabilities)!=set(choices) or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in probabilities.values()) or abs(sum(probabilities.values())-1)>1e-5: raise SelectionError('Invalid probabilities','invalid_response')
        confidence=answer.get('confidence')
        if confidence is None: raise SelectionError('Missing confidence','invalid_response')
        if confidence is not None and (type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1): raise SelectionError('Invalid confidence','invalid_response')
        if min_confidence is not None and (confidence is None or confidence<min_confidence): raise SelectionError('Low Jev confidence','low_confidence')
        return {'choice':answer['choice'],'confidence':confidence}
