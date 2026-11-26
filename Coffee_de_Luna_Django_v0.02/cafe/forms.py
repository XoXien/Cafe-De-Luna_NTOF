from decimal import Decimal
from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.contrib.auth.models import User
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import Category, Ingredient, Product, Purchase, RecipeItem
from .permissions import is_team

class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'Enter your username', 'autofocus': True}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Enter your password'}))
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not is_team(user):
            raise forms.ValidationError('Use customer sign in for this account.', code='customer_account')

class CustomerLoginForm(AuthenticationForm):
    username = forms.EmailField(label='Email address', max_length=150,
        widget=forms.EmailInput(attrs={'autocomplete': 'username', 'placeholder': 'you@example.com'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'placeholder': 'Your password'}))
    def clean_username(self):
        return self.cleaned_data['username'].strip().lower()

class CustomerRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    email = forms.EmailField(max_length=150, widget=forms.EmailInput(attrs={'autocomplete': 'email', 'placeholder': 'you@example.com'}))
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['first_name', 'last_name', 'email']
    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError('An account already uses this email. Please sign in.')
        return email
    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user

class IngredientForm(forms.ModelForm):
    opening_stock = forms.DecimalField(max_digits=13, decimal_places=3, min_value=0, initial=0, required=False,
                                       help_text='Starting quantity, in the selected unit. Future changes use Receive stock or Adjust.')
    class Meta:
        model = Ingredient
        fields = ['name', 'sku', 'unit', 'storage_type', 'opening_stock', 'reorder_level', 'cost_per_unit',
                  'notes', 'is_estimated', 'is_active']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['storage_type'].required = False
        if self.instance.pk:
            self.fields.pop('opening_stock')
            self.fields['unit'].disabled = True
        self.fields['cost_per_unit'].help_text = 'Cost per gram, milliliter, or piece. Deliveries update the weighted average.'
    def clean_storage_type(self):
        return self.cleaned_data.get('storage_type') or self.instance.storage_type or 'unspecified'

class AddStockForm(forms.ModelForm):
    unit_cost = forms.DecimalField(max_digits=12, decimal_places=4, min_value=0, required=False,
        label='Cost per unit', help_text='Optional. Leave blank to use the ingredient’s current average cost per g, ml, or piece.')
    class Meta:
        model = Purchase
        fields = ['ingredient', 'quantity', 'unit_cost', 'notes']
        labels = {'quantity': 'Quantity to add'}
        widgets = {'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional stock note'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ingredient'].queryset = Ingredient.objects.filter(is_active=True)
        self.fields['quantity'].help_text = 'Enter a positive amount in the selected ingredient’s unit: g, ml, or pcs. Example: 1 kg = 1,000 g.'

class AdjustmentForm(forms.Form):
    ingredient = forms.ModelChoiceField(queryset=Ingredient.objects.all())
    kind = forms.ChoiceField(choices=[('adjust', 'Stock correction'), ('waste', 'Waste / spoilage')])
    quantity = forms.DecimalField(max_digits=13, decimal_places=3,
        help_text='Signed change in base units. Use -100 to remove 100; use 100 to add 100.')
    reason = forms.CharField(max_length=250, widget=forms.Textarea(attrs={'rows': 3}))
    def clean(self):
        data = super().clean()
        qty = data.get('quantity', 0)
        if not qty:
            self.add_error('quantity', 'Enter a non-zero quantity.')
        if data.get('kind') == 'waste' and qty > 0:
            self.add_error('quantity', 'Use a negative quantity to record waste.')
        return data

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'menu_name', 'variant_label', 'category', 'description', 'price', 'artwork', 'image',
                  'badge', 'is_add_on', 'customization_type', 'max_per_drink', 'replaces_ingredient',
                  'recipe_is_estimated', 'recipe_notes', 'is_active']
        widgets = {'description': forms.Textarea(attrs={'rows': 2}), 'recipe_notes': forms.Textarea(attrs={'rows': 2})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customization_type'].required = False
        self.fields['max_per_drink'].required = False
        self.fields['customization_type'].help_text = 'Used only for add-ons. Customers choose these inside their drink’s Customize screen.'
        self.fields['max_per_drink'].help_text = '1–3 extra portions per drink. Milk and cream choices always allow one.'
    def clean(self):
        data = super().clean()
        data['customization_type'] = data.get('customization_type') or self.instance.customization_type or 'extra'
        data['max_per_drink'] = data.get('max_per_drink') or self.instance.max_per_drink or 1
        if data.get('replaces_ingredient') and (not data.get('is_add_on') or data['customization_type'] != 'milk'):
            self.add_error('replaces_ingredient', 'Only a milk add-on can replace an ingredient.')
        return data
    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and hasattr(image, 'size') and image.size > 4 * 1024 * 1024:
            raise forms.ValidationError('Choose an image smaller than 4 MB.')
        return image

class RecipeSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        rows = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')]
        if not rows:
            raise forms.ValidationError('Add at least one ingredient so inventory can track this menu item.')
        if self.instance.replaces_ingredient_id:
            replacement = self.instance.replaces_ingredient
            if (len(rows) != 1 or rows[0].cleaned_data['ingredient'].pk == replacement.pk
                    or rows[0].cleaned_data['ingredient'].unit != replacement.unit):
                raise forms.ValidationError('A milk replacement needs exactly one different ingredient in the same unit as the milk it replaces.')

RecipeFormSet = inlineformset_factory(Product, RecipeItem, formset=RecipeSet,
    fields=['ingredient', 'quantity'], extra=1, can_delete=True)

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'sort_order']

class StaffForm(UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(choices=[('cashier', 'Cashier'), ('manager', 'Manager')])
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'role']
    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Another account already uses this email.')
        return email

class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Another account already uses this email.')
        return email
