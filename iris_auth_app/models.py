import numpy as np
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class IrisUser(AbstractUser):
    display_name = models.CharField(max_length=120, blank=True)
    student_id = models.CharField(max_length=64, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.display_name:
            self.display_name = self.get_full_name() or self.username
        super().save(*args, **kwargs)


class IrisTemplate(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='iris_template',
    )
    code = models.BinaryField(help_text='Serialized iris code bytes.')
    mask = models.BinaryField(help_text='Serialized valid-mask bytes.')
    code_shape = models.CharField(max_length=32, default='256,512')
    code_dtype = models.CharField(max_length=16, default='uint8')
    mask_shape = models.CharField(max_length=32, default='256,512')
    mask_dtype = models.CharField(max_length=16, default='uint8')
    encoding_version = models.CharField(max_length=64, default='gabor-v1')
    enrollment_status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('active', 'Active'), ('rejected', 'Rejected')],
        default='pending',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @staticmethod
    def _parse_shape(shape_value):
        if not shape_value:
            return ()
        normalized_shape = str(shape_value).strip().strip('()[]')
        return tuple(int(part.strip()) for part in normalized_shape.split(',') if part.strip())

    @staticmethod
    def serialize_array(array):
        arr = np.asarray(array, dtype=np.uint8)
        return arr.tobytes(), arr.shape, arr.dtype.name

    @classmethod
    def deserialize_array(cls, payload, shape_value, dtype_name):
        ALLOWED_DTYPES = {'uint8', 'int8'}
        if dtype_name not in ALLOWED_DTYPES:
            raise ValidationError(f'Unsupported array dtype: {dtype_name}')
        if payload in (None, b''):
            raise ValidationError('Template payload is empty.')
        shape = cls._parse_shape(shape_value)
        if not shape:
            raise ValidationError('Template shape is missing.')
        try:
            array = np.frombuffer(payload, dtype=np.dtype(dtype_name)).reshape(shape)
        except (TypeError, ValueError, AttributeError):
            raise ValidationError('Template payload does not match the saved shape or dtype.')
        return array

    @classmethod
    def create_for_user(cls, user, code_array, mask_array, *, encoding_version='gabor-v1'):
        code_bytes, code_shape, code_dtype = cls.serialize_array(code_array)
        mask_bytes, mask_shape, mask_dtype = cls.serialize_array(mask_array)

        return cls.objects.create(
            user=user,
            code=code_bytes,
            mask=mask_bytes,
            code_shape=','.join(str(dim) for dim in code_shape),
            code_dtype=code_dtype,
            mask_shape=','.join(str(dim) for dim in mask_shape),
            mask_dtype=mask_dtype,
            encoding_version=encoding_version,
            enrollment_status='active',
        )

    def validate_template(self):
        if not self.code or not self.mask:
            raise ValidationError('Template data is missing.')

        code = self.deserialize_array(self.code, self.code_shape, self.code_dtype)
        mask = self.deserialize_array(self.mask, self.mask_shape, self.mask_dtype)

        if code.shape != self._parse_shape(self.code_shape):
            raise ValidationError('Stored code shape does not match the saved metadata.')
        if mask.shape != self._parse_shape(self.mask_shape):
            raise ValidationError('Stored mask shape does not match the saved metadata.')
        if code.dtype.name != self.code_dtype or mask.dtype.name != self.mask_dtype:
            raise ValidationError('Stored array dtype does not match the metadata.')

        if code.size == 0 or mask.size == 0:
            raise ValidationError('Template arrays cannot be empty.')

        return code, mask

    def __str__(self):
        return f'Iris template for {self.user.username}'
