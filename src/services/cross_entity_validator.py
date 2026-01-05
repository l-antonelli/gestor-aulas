"""
Cross-entity validation module for relationship constraints.

This module validates constraints that span multiple related entities,
ensuring data integrity at the relationship level.
"""

from typing import List, Tuple, Callable, Any, Optional, Dict
from pydantic import BaseModel
from sqlmodel import Session, select

from src.services.relationship_metadata import RelationshipMetadata
from src.services.relationship_registry import RelationshipRegistry


class CrossEntityValidator:
    """
    Validates constraints across related entities.
    
    This class provides methods to validate various types of cross-entity
    constraints including sum constraints, uniqueness, and conflicts.
    """
    
    @staticmethod
    def validate_relationship(
        parent_instance: BaseModel,
        child_instance: BaseModel,
        validation_rules: List[Callable],
    ) -> Tuple[bool, List[str]]:
        """
        Validate a relationship between parent and child using custom rules.
        
        Args:
            parent_instance: The parent entity instance
            child_instance: The child entity instance
            validation_rules: List of validation functions that take (parent, child)
                            and return (is_valid, error_message)
        
        Returns:
            Tuple of (is_valid, list_of_error_messages)
            
        Example:
            >>> def validate_cupo(parent, child):
            ...     if child.cupo > parent.cupo:
            ...         return False, "Child cupo exceeds parent cupo"
            ...     return True, ""
            >>> is_valid, errors = CrossEntityValidator.validate_relationship(
            ...     materia, comision, [validate_cupo]
            ... )
        """
        errors = []
        
        for rule in validation_rules:
            try:
                result = rule(parent_instance, child_instance)
                
                # Handle different return formats
                if isinstance(result, tuple):
                    is_valid, error_msg = result
                    if not is_valid and error_msg:
                        errors.append(error_msg)
                elif isinstance(result, bool):
                    if not result:
                        errors.append(f"Validation rule {rule.__name__} failed")
                else:
                    errors.append(f"Invalid validation rule return type: {type(result)}")
                    
            except Exception as e:
                errors.append(f"Validation rule {rule.__name__} raised exception: {str(e)}")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_sum_constraint(
        parent_instance: BaseModel,
        child_instances: List[BaseModel],
        parent_field: str,
        child_field: str,
    ) -> Tuple[bool, str]:
        """
        Validate that sum of child field values doesn't exceed parent field value.
        
        This is useful for constraints like "sum of Comisión cupos <= Materia cupo".
        
        Args:
            parent_instance: The parent entity instance
            child_instances: List of child entity instances
            parent_field: Name of the field in parent to compare against
            child_field: Name of the field in children to sum
        
        Returns:
            Tuple of (is_valid, error_message)
            
        Example:
            >>> # Validate that sum of comision cupos doesn't exceed materia cupo
            >>> is_valid, error = CrossEntityValidator.validate_sum_constraint(
            ...     materia, comisiones, "cupo", "cupo"
            ... )
        """
        try:
            # Get parent field value
            parent_value = getattr(parent_instance, parent_field, None)
            if parent_value is None:
                return False, f"Parent field '{parent_field}' not found or is None"
            
            # Sum child field values
            child_sum = 0
            for child in child_instances:
                child_value = getattr(child, child_field, None)
                if child_value is None:
                    return False, f"Child field '{child_field}' not found or is None in one or more children"
                child_sum += child_value
            
            # Validate constraint
            if child_sum > parent_value:
                return False, (
                    f"Sum constraint violation: sum of {child_field} ({child_sum}) "
                    f"exceeds parent {parent_field} ({parent_value})"
                )
            
            return True, ""
            
        except Exception as e:
            return False, f"Error validating sum constraint: {str(e)}"
    
    @staticmethod
    def validate_uniqueness_constraint(
        child_instance: BaseModel,
        existing_children: List[BaseModel],
        unique_fields: List[str],
    ) -> Tuple[bool, str]:
        """
        Validate that child instance is unique based on specified fields.
        
        This prevents duplicate relationships like two Comisiones with the
        same materia_codigo and numero.
        
        Args:
            child_instance: The new child entity instance to validate
            existing_children: List of existing child entities
            unique_fields: List of field names that must be unique together
        
        Returns:
            Tuple of (is_valid, error_message)
            
        Example:
            >>> # Validate that no two comisiones have same materia_codigo and numero
            >>> is_valid, error = CrossEntityValidator.validate_uniqueness_constraint(
            ...     new_comision, existing_comisiones, ["materia_codigo", "numero"]
            ... )
        """
        try:
            # Get values from new instance
            new_values = {}
            for field in unique_fields:
                value = getattr(child_instance, field, None)
                if value is None:
                    return False, f"Field '{field}' not found or is None in new instance"
                new_values[field] = value
            
            # Check against existing instances
            for existing in existing_children:
                # Skip if comparing with itself (same id)
                if hasattr(child_instance, 'id') and hasattr(existing, 'id'):
                    if child_instance.id == existing.id:
                        continue
                
                # Check if all unique fields match
                all_match = True
                for field in unique_fields:
                    existing_value = getattr(existing, field, None)
                    if existing_value != new_values[field]:
                        all_match = False
                        break
                
                if all_match:
                    field_str = ", ".join([f"{f}={new_values[f]}" for f in unique_fields])
                    return False, f"Duplicate constraint violation: entity with {field_str} already exists"
            
            return True, ""
            
        except Exception as e:
            return False, f"Error validating uniqueness constraint: {str(e)}"
    
    @staticmethod
    def validate_conflict_constraint(
        new_instance: BaseModel,
        existing_instances: List[BaseModel],
        conflict_fields: List[str],
        conflict_checker: Optional[Callable[[BaseModel, BaseModel], bool]] = None,
    ) -> Tuple[bool, str]:
        """
        Validate that new instance doesn't conflict with existing instances.
        
        This is useful for constraints like "Aula can't have overlapping
        AsignacionAula at same time".
        
        Args:
            new_instance: The new entity instance to validate
            existing_instances: List of existing entities to check against
            conflict_fields: List of field names to check for conflicts
            conflict_checker: Optional custom function to determine if two instances
                            conflict. Takes (new, existing) and returns True if conflict.
                            If None, uses simple field equality check.
        
        Returns:
            Tuple of (is_valid, error_message)
            
        Example:
            >>> # Validate that aula assignment doesn't conflict with existing ones
            >>> def check_time_overlap(new, existing):
            ...     # Custom logic to check if time slots overlap
            ...     return new.horario_id == existing.horario_id
            >>> is_valid, error = CrossEntityValidator.validate_conflict_constraint(
            ...     new_asignacion, existing_asignaciones, ["aula_id", "horario_id"],
            ...     conflict_checker=check_time_overlap
            ... )
        """
        try:
            # Get values from new instance
            new_values = {}
            for field in conflict_fields:
                value = getattr(new_instance, field, None)
                if value is None:
                    return False, f"Field '{field}' not found or is None in new instance"
                new_values[field] = value
            
            # Check against existing instances
            for existing in existing_instances:
                # Skip if comparing with itself (same id)
                if hasattr(new_instance, 'id') and hasattr(existing, 'id'):
                    if new_instance.id == existing.id:
                        continue
                
                # Use custom conflict checker if provided
                if conflict_checker:
                    if conflict_checker(new_instance, existing):
                        return False, "Conflict detected with existing entity"
                else:
                    # Default: check if all conflict fields match
                    all_match = True
                    for field in conflict_fields:
                        existing_value = getattr(existing, field, None)
                        if existing_value != new_values[field]:
                            all_match = False
                            break
                    
                    if all_match:
                        field_str = ", ".join([f"{f}={new_values[f]}" for f in conflict_fields])
                        return False, f"Conflict detected: entity with {field_str} already exists"
            
            return True, ""
            
        except Exception as e:
            return False, f"Error validating conflict constraint: {str(e)}"
    
    @staticmethod
    def get_constraint_suggestions(
        parent_instance: BaseModel,
        child_instances: List[BaseModel],
        validation_error: str,
    ) -> List[str]:
        """
        Get suggestions for resolving constraint violations.
        
        Analyzes the validation error and provides actionable suggestions
        for the user to resolve the issue.
        
        Args:
            parent_instance: The parent entity instance
            child_instances: List of child entity instances
            validation_error: The validation error message
        
        Returns:
            List of suggestion strings
            
        Example:
            >>> suggestions = CrossEntityValidator.get_constraint_suggestions(
            ...     materia, comisiones, "Sum constraint violation: sum of cupo (100) exceeds parent cupo (80)"
            ... )
            >>> # Returns: ["Reduce total Comisión cupo by 20 to comply with Materia limit"]
        """
        suggestions = []
        
        # Parse sum constraint violations
        if "sum constraint violation" in validation_error.lower():
            # Try to extract numbers from error message
            import re
            numbers = re.findall(r'\((\d+)\)', validation_error)
            
            if len(numbers) >= 2:
                child_sum = int(numbers[0])
                parent_value = int(numbers[1])
                difference = child_sum - parent_value
                
                # Extract field names
                field_match = re.search(r'sum of (\w+).*parent (\w+)', validation_error)
                if field_match:
                    child_field = field_match.group(1)
                    parent_field = field_match.group(2)
                    
                    suggestions.append(
                        f"Reduce total child {child_field} by {difference} to comply with parent {parent_field} limit"
                    )
                    suggestions.append(
                        f"Alternatively, increase parent {parent_field} from {parent_value} to at least {child_sum}"
                    )
        
        # Parse duplicate constraint violations
        elif "duplicate constraint violation" in validation_error.lower():
            suggestions.append("Change the unique field values to avoid duplication")
            suggestions.append("Delete or modify the existing entity with the same values")
        
        # Parse conflict constraint violations
        elif "conflict detected" in validation_error.lower():
            suggestions.append("Choose a different time slot or resource to avoid conflicts")
            suggestions.append("Modify the existing conflicting entity")
        
        # Generic suggestions if no specific pattern matched
        if not suggestions:
            suggestions.append("Review the constraint violation and adjust entity values accordingly")
            suggestions.append("Contact system administrator if the constraint seems incorrect")
        
        return suggestions
    
    @staticmethod
    def validate_parent_child_constraint(
        parent_instance: BaseModel,
        child_instances: List[BaseModel],
        relationship_metadata: RelationshipMetadata,
    ) -> Tuple[bool, List[str]]:
        """
        Validate all constraints defined in relationship metadata.
        
        This is a convenience method that runs all validation rules defined
        in the relationship metadata.
        
        Args:
            parent_instance: The parent entity instance
            child_instances: List of child entity instances
            relationship_metadata: The relationship metadata containing validation rules
        
        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        all_errors = []
        
        # Run custom validation rules for each child
        for child in child_instances:
            is_valid, errors = CrossEntityValidator.validate_relationship(
                parent_instance,
                child,
                relationship_metadata.validation_rules
            )
            if not is_valid:
                all_errors.extend(errors)
        
        return len(all_errors) == 0, all_errors
